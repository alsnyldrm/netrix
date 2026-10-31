"""Compact, versioned projections of the latest device evidence. No network I/O."""

import ipaddress
from collections import OrderedDict
from datetime import timedelta
from threading import RLock

from sqlalchemy import func, select

from .. import models as m
from ..core import now

# Immutable observation versions, shared by API threads. Bounded by devices and facts;
# a new observation/version, archive, VRF change or 24h expiry is checked on every read.
_cache = OrderedDict()
_cache_lock = RLock()
_MAX_SNAPSHOTS = 256
_MAX_FACTS = 400000


def device_rank(device):
    name = device.device_type.name.casefold() if device.device_type else device.kind.casefold()
    if "backbone" in name or "bakbone" in name:
        return 3
    if device.kind == "firewall" or "firewall" in name:
        return 4
    return 2  # Corner/access switches and explicitly managed generic switches.


def identity_rank(observation, devices):
    if observation.source == "vcenter":
        return 0
    if observation.source == "windows_dhcp":
        return 1
    device = devices.get(observation.data.get("device_id"))
    if observation.source == "inventory" and device:
        return device_rank(device)
    return 5 if observation.source == "inventory" else 6


def project_snapshot(evidence):
    from .service import normalized_mac

    tables = evidence.get("tables") or {}
    macs, arp, hosts, uplinks = {}, {}, {}, set()
    bridges = tables.get("bridge_ifindex") or {}
    for table in ("fdb_port", "vlan_fdb_port"):
        for key, bridge in (tables.get(table) or {}).items():
            values = key.split(".")[-6:]
            try:
                if len(values) != 6:
                    continue
                raw = bytes(int(v) for v in values)
                mac = raw.hex(":")
                index = int(bridges[str(bridge)])
                if index > 0:
                    macs.setdefault(mac, set()).add(index)
            except (ValueError, KeyError, TypeError):
                continue
    for key, value in (tables.get("arp_mac") or {}).items():
        parts = key.split(".")
        try:
            address = str(ipaddress.IPv4Address(".".join(parts[-4:])))
            index = int(parts[-5])
        except (ValueError, IndexError):
            continue
        mac = normalized_mac(value)
        if mac:
            arp.setdefault(address, []).append((mac, index))
    for key, value in (tables.get("ndp_mac") or {}).items():
        try:
            parts = [int(v) for v in key.split(".")]
            if (
                len(parts) < 3
                or parts[1] not in (1, 2)
                or parts[2] not in (4, 16)
                or len(parts[3:]) != parts[2]
            ):
                continue
            address = str(ipaddress.ip_address(bytes(parts[3:])))
        except ValueError:
            continue
        mac = normalized_mac(value)
        if mac:
            arp.setdefault(address, []).append((mac, parts[0]))
    for neighbor in evidence.get("neighbors") or []:
        local = neighbor.get("interface_name")
        data = neighbor.get("evidence") or {}
        aggregate = data.get("local_aggregate") or {}
        port = aggregate.get("name") or local
        uplinks.update(v for v in (local, port) if v)
        # A neighbor's management IP proves the endpoint of a port/aggregate.
        # Chassis MACs are NOT substituted for the IP's MAC (bonds can differ).
        for protocol in ("lldp", "cdp"):
            address = (data.get(protocol) or {}).get("management_address")
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                continue
            if port:
                key = (address, port)
                item = hosts.setdefault(key, {"name": neighbor.get("remote_name") or "", "members": set()})
                if local and aggregate.get("name"):
                    item["members"].add(local)
    detail = evidence.get("neighbor_detail") or {}
    for member, aggregate in (detail.get("trunks") or {}).items():
        if member in uplinks and aggregate.get("name"):
            uplinks.add(aggregate["name"])
    root = (detail.get("spanning_tree") or {}).get("port")
    if root:
        uplinks.add(root)
    return {
        "macs": {mac: tuple(sorted(indices)) for mac, indices in macs.items()},
        "arp": arp,
        "hosts": {key: {**value, "members": sorted(value["members"])} for key, value in hosts.items()},
        "uplinks": uplinks,
    }


def latest_snapshots(db, device_ids):
    if not device_ids:
        return {}
    ranked = (
        select(
            m.Observation.id,
            m.Observation.device_id,
            m.Observation.created_at,
            m.Observation.updated_at,
            func.row_number()
            .over(
                partition_by=m.Observation.device_id,
                order_by=(m.Observation.created_at.desc(), m.Observation.id.desc()),
            )
            .label("position"),
        )
        .where(
            m.Observation.device_id.in_(device_ids),
            m.Observation.source.in_(("snmpv3", "snmpv2c")),
            m.Observation.created_at >= now() - timedelta(hours=24),
        )
        .subquery()
    )
    versions = db.execute(select(ranked).where(ranked.c.position == 1)).all()
    found, missing = {}, {}
    bind = db.get_bind()
    with _cache_lock:
        for row in versions:
            key = (bind, row.id, row.updated_at)
            if key in _cache:
                found[row.id] = _cache[key]
                _cache.move_to_end(key)
            else:
                missing[row.id] = key
    if missing:
        for identifier, evidence in db.execute(
            select(m.Observation.id, m.Observation.evidence).where(m.Observation.id.in_(missing))
        ):
            projected = project_snapshot(evidence)
            found[identifier] = projected
            with _cache_lock:
                _cache[missing[identifier]] = projected
                while (
                    len(_cache) > _MAX_SNAPSHOTS or sum(len(v["macs"]) for v in _cache.values()) > _MAX_FACTS
                ):
                    _cache.popitem(last=False)
    return {row.device_id: (found[row.id], row.created_at) for row in versions if row.id in found}
