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
    macs, arp, hosts, uplinks, neighbor_macs = {}, {}, {}, set(), {}
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
        lldp = data.get("lldp") or {}
        # An AP/server advertising its own MAC is the endpoint, not a transit switch.
        for value in (
            lldp.get("chassis_id") if lldp.get("chassis_subtype") == 4 else None,
            lldp.get("port_id") if lldp.get("port_subtype") == 3 else None,
        ):
            mac = normalized_mac(value)
            if mac and port:
                neighbor_macs[(mac, port)] = {"name": neighbor.get("remote_name") or "", "members": []}
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
        "neighbor_macs": neighbor_macs,
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


def managed_endpoints(links, rows, grouped, devices, snapshots):
    """Endpoint names from operator corrections or direct LLDP/CDP advertisements.

    A short hostname may match one qualified name, never multiple domains. Deleted,
    stale, excluded links and cross-VRF names cannot override current evidence.
    """
    names = {}
    for link in links:
        name = link.manual_remote_name
        if not name:
            # A protocol-advertised hostname is direct endpoint evidence. Do not
            # promote arbitrary FDB hops, descriptions or inferred inventory names.
            evidence = link.evidence or {}
            advertised_names = [
                (evidence.get("lldp") or {}).get("system_name"),
                (evidence.get("cdp") or {}).get("device_id"),
            ]
            name = next((n for n in advertised_names if n and n == link.remote_name), "")
        if not name:
            continue
        name = name.rstrip(".").casefold()
        device = devices[link.device_id]
        names.setdefault((device.vrf_id, name), []).append(link)
    advertised = {}
    for device_id, (snapshot, _) in snapshots.items():
        for (address, _), host in snapshot["hosts"].items():
            if host["name"]:
                advertised.setdefault((devices[device_id].vrf_id, address), set()).add(
                    host["name"].rstrip(".").casefold()
                )
    result = {}
    for row in rows or []:
        ordered = sorted(
            (
                o
                for o in grouped[row.id]
                if o.observed_at >= now() - timedelta(hours=24) and o.data.get("present", True)
            ),
            key=lambda o: (identity_rank(o, devices), -o.observed_at.timestamp()),
        )
        name = (
            (row.hostname or next((o.data.get("hostname") for o in ordered if o.data.get("hostname")), ""))
            .rstrip(".")
            .casefold()
        )
        if not name:
            candidates = advertised.get((row.vrf_id, row.address), set())
            if len(candidates) != 1:
                continue
            name = next(iter(candidates))
        matches = names.get((row.vrf_id, name), [])
        if not matches:
            aliases = [
                value
                for (vrf, label), value in names.items()
                if vrf == row.vrf_id
                and label.split(".")[0] == name.split(".")[0]
                and ("." not in label or "." not in name)
            ]
            matches = aliases[0] if len(aliases) == 1 else []
        corrected = [link for link in matches if link.manual_remote_name]
        if corrected:
            # Corrections choose the endpoint's connection layer (e.g. backbone
            # data NICs rather than management NICs). Include redundant peers at
            # that layer even when their hostname came directly from LLDP/CDP.
            ranks = {device_rank(devices[link.device_id]) for link in corrected}
            matches = [link for link in matches if device_rank(devices[link.device_id]) in ranks]
        elif matches:
            rank = min(device_rank(devices[link.device_id]) for link in matches)
            matches = [link for link in matches if device_rank(devices[link.device_id]) == rank]
        result[row.id] = matches
    return result
