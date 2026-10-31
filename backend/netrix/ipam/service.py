"""IPAM policies, source observations and cross-device endpoint correlation."""

import ipaddress
import json
import re
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import or_, select, tuple_

from .. import models as m
from ..core import now
from ..identity.security import audit, encrypt
from ..services import get, in_scope, lock_vrf, publish, serialize


def normalized_mac(value):
    compact = re.sub(r"[:.\-]", "", value or "").lower()
    # DHCP may prefix an Ethernet hardware identifier with 01.
    if len(compact) == 14 and compact.startswith("01"):
        compact = compact[2:]
    if not re.fullmatch("[0-9a-f]{12}", compact) or compact in ("000000000000", "ffffffffffff"):
        return ""
    return ":".join(compact[i : i + 2] for i in range(0, 12, 2))


def save_settings(db, prefix_id, payload, user):
    prefix = get(db, m.Prefix, prefix_id)
    data = payload.model_dump()
    if "scope_id" not in payload.model_fields_set:
        data.pop("scope_id", None)
    if payload.dns_server_id:
        get(db, m.DNSServer, payload.dns_server_id)
    if payload.vlan_device_id:
        device = get(db, m.Device, payload.vlan_device_id)
        if device.archived or device.vrf_id != prefix.vrf_id:
            raise HTTPException(422, "VLAN cihazı aynı VRF içinde ve envanterde etkin olmalı")
    if payload.scope_id:
        scope = get(db, m.Scope, payload.scope_id)
        network, allowed = ipaddress.ip_network(prefix.cidr), ipaddress.ip_network(scope.cidr)
        if (
            scope.vrf_id != prefix.vrf_id
            or network.version != allowed.version
            or not network.subnet_of(allowed)
        ):
            raise HTTPException(422, "Ağ bloğu seçilen yetkili kapsamın içinde olmalı")
    authorized = payload.scan_authorized
    if authorized is None:
        authorized = bool(payload.scope_id) or prefix.scan_authorized
    data["scan_authorized"] = authorized
    if (
        not authorized
        and (payload.ping_enabled or payload.discovery_enabled)
        and payload.scan_authorized is not False
    ):
        raise HTTPException(422, "Önce ağ bloğunda keşif yetkisini işaretleyin")
    if not authorized:
        data["ping_enabled"] = data["discovery_enabled"] = False
    for key, value in data.items():
        setattr(prefix, key, value)
    audit(db, user, "ipam_settings", "prefixes", prefix.id, "Ağ bloğu ayarları güncellendi")
    db.commit()
    publish()
    return prefix_summary(db, prefix)


def require_scope(db, prefix, scope_id=None):
    if not prefix.scan_authorized:
        raise HTTPException(422, "Ağ bloğu ayarlarında keşif yetkisini işaretleyin")
    scope = db.get(m.Scope, scope_id or prefix.scope_id) if scope_id or prefix.scope_id else None
    network = ipaddress.ip_network(prefix.cidr)
    exclusions, seeds = [], []
    if scope:
        allowed = ipaddress.ip_network(scope.cidr)
        if (
            scope.vrf_id == prefix.vrf_id
            and network.version == allowed.version
            and network.subnet_of(allowed)
        ):
            exclusions, seeds = scope.exclusions, scope.seeds
    return SimpleNamespace(
        enabled=True, cidr=prefix.cidr, vrf_id=prefix.vrf_id, exclusions=exclusions, seeds=seeds
    )


def ping_availability(observations, *, at=None):
    """Only a recent, explicit ICMP response establishes active IP usage."""
    latest = max(
        (o for o in observations if o.source == "icmp"),
        key=lambda o: (o.observed_at, o.id),
        default=None,
    )
    if (
        not latest
        or latest.observed_at < (at or now()) - timedelta(hours=24)
        or not latest.data.get("present", True)
    ):
        return "unknown"
    return {"reachable": "active", "no_reply": "passive"}.get(latest.data.get("reachability"), "unknown")


def active_address_ids(db, vrf_ids):
    # Batch lightweight ping facts; do not resolve device topology to count IPs.
    latest = {}
    for address_id, data in db.execute(
        select(m.IPObservation.address_id, m.IPObservation.data)
        .join(m.IPAddress, m.IPAddress.id == m.IPObservation.address_id)
        .where(
            m.IPAddress.vrf_id.in_(vrf_ids),
            m.IPObservation.source == "icmp",
            m.IPObservation.observed_at >= now() - timedelta(hours=24),
        )
        .order_by(m.IPObservation.observed_at.desc(), m.IPObservation.id.desc())
    ):
        latest.setdefault(address_id, data)
    return {
        id
        for id, data in latest.items()
        if data.get("present", True) and data.get("reachability") == "reachable"
    }


def prefix_summaries(db, prefixes):
    if not prefixes:
        return []
    assignments = {}
    vrf_ids = {p.vrf_id for p in prefixes}
    active = active_address_ids(db, vrf_ids)
    for id, vrf_id, address, status in db.execute(
        select(m.IPAddress.id, m.IPAddress.vrf_id, m.IPAddress.address, m.IPAddress.status).where(
            m.IPAddress.vrf_id.in_(vrf_ids)
        )
    ):
        assignments.setdefault(vrf_id, []).append((id, ipaddress.ip_address(address), status))
    vlans = {
        v.id: v
        for v in db.scalars(select(m.VLAN).where(m.VLAN.id.in_({p.vlan_id for p in prefixes if p.vlan_id})))
    }
    result = []
    for prefix in prefixes:
        network = ipaddress.ip_network(prefix.cidr)
        capacity = network.num_addresses - (2 if network.version == 4 and network.prefixlen < 31 else 0)
        counts = {"active": 0, "reserved": 0}
        used = 0
        for id, ip, status in assignments.get(prefix.vrf_id, ()):
            if ip in network and not (
                network.version == 4
                and network.prefixlen < 31
                and ip in (network.network_address, network.broadcast_address)
            ):
                if status in counts:
                    counts[status] += 1
                used += int(id in active)
        vlan = vlans.get(prefix.vlan_id)
        item = serialize(prefix)
        item.update(
            capacity=str(capacity),
            used=used,
            assigned_active=counts["active"],
            reserved=counts["reserved"],
            utilization=round(used * 100 / capacity, 2),
            threshold_exceeded=used * 100 >= capacity * prefix.warning_threshold,
            vlan=f"VLAN-{vlan.vid} / {vlan.name}" if vlan else "VLAN belirtilmedi",
        )
        item["display_name"] = f"{item['vlan']} | {prefix.cidr}"
        result.append(item)
    return result


def prefix_summary(db, prefix):
    return prefix_summaries(db, [prefix])[0]


def targets(db, prefix, discover=False):
    scope = require_scope(db, prefix)
    network = ipaddress.ip_network(prefix.cidr)
    if discover:
        if network.version == 6 or network.num_addresses > 4096:
            if not scope.seeds:
                raise HTTPException(422, "IPv6 ve 4096 adresten geniş ağlarda kapsam hedef listesi gerekli")
            candidates = scope.seeds
        else:
            candidates = map(str, network.hosts())
    else:
        candidates = db.scalars(select(m.IPAddress.address).where(m.IPAddress.prefix_id == prefix.id)).all()
    return [
        a
        for a in candidates
        if ipaddress.ip_address(a) in network
        and in_scope(a, scope)
        and not any(
            (
                ipaddress.ip_address(a).is_multicast,
                ipaddress.ip_address(a).is_loopback,
                ipaddress.ip_address(a).is_link_local,
                ipaddress.ip_address(a).is_unspecified,
            )
        )
    ]


def save_integration(db, payload, user, id=None):
    row = get(db, m.Integration, id) if id else m.Integration()
    data = payload.model_dump(exclude={"username", "password"})
    for prefix_id in payload.prefix_ids:
        get(db, m.Prefix, prefix_id)
    # One source cannot disambiguate overlapping address spaces.
    prefixes = [get(db, m.Prefix, p) for p in payload.prefix_ids]
    for left in prefixes:
        for right in prefixes:
            a, b = ipaddress.ip_network(left.cidr), ipaddress.ip_network(right.cidr)
            if left.vrf_id != right.vrf_id and a.version == b.version and a.overlaps(b):
                raise HTTPException(422, "Çakışan farklı VRF ağları için ayrı entegrasyon tanımlayın")
    changed_target = id and (row.host != payload.host or row.port != payload.port or row.kind != payload.kind)
    if not id or changed_target or payload.username or payload.password:
        if not payload.username or not payload.password:
            raise HTTPException(422, "Kullanıcı ve parola birlikte gerekli; sunucu değişiminde yeniden girin")
        row.encrypted_secret = encrypt(
            json.dumps({"username": payload.username, "password": payload.password})
        )
    for key, value in data.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    audit(db, user, "integration_save", "integrations", row.id, "Entegrasyon ayarları kaydedildi")
    db.commit()
    publish()
    return serialize(row)


def prefix_for(db, address, prefixes):
    ip = ipaddress.ip_address(address)
    eligible = [p for p in prefixes if ip in ipaddress.ip_network(p.cidr)]
    eligible.sort(key=lambda p: ipaddress.ip_network(p.cidr).prefixlen, reverse=True)
    return eligible[0] if eligible else None


def observe(db, prefix, address, source, source_key, data, *, create=True):
    ip = ipaddress.ip_address(address)
    network = ipaddress.ip_network(prefix.cidr)
    if ip not in network or ip.is_multicast or ip.is_link_local or ip.is_loopback or ip.is_unspecified:
        return None
    if (
        network.version == 4
        and network.prefixlen < 31
        and ip in (network.network_address, network.broadcast_address)
    ):
        return None
    lock_vrf(db, prefix.vrf_id)
    row = db.scalar(
        select(m.IPAddress).where(m.IPAddress.vrf_id == prefix.vrf_id, m.IPAddress.address == str(ip))
    )
    if not row and not create:
        return None
    if not row:
        row = m.IPAddress(
            address=str(ip),
            vrf_id=prefix.vrf_id,
            prefix_id=prefix.id,
            status="reserved" if source == "windows_dhcp" and data.get("reserved", True) else "active",
        )
        db.add(row)
        db.flush()
    observed = db.scalar(
        select(m.IPObservation).where(
            m.IPObservation.address_id == row.id,
            m.IPObservation.source == source,
            m.IPObservation.source_key == source_key,
        )
    )
    if not observed:
        observed = m.IPObservation(address_id=row.id, source=source, source_key=source_key)
        db.add(observed)
    elif observed.data != data:
        db.add(
            m.Event(
                kind="ip_observation_change",
                message=f"{row.address}: {source} bilgisi değişti",
                details={"address_id": row.id, "source": source, "previous": observed.data, "current": data},
            )
        )
    observed.data, observed.observed_at = data, now()
    db.flush()
    return row


def observations(db, rows):
    ids = [r.id for r in rows]
    result = {id: [] for id in ids}
    for obs in db.scalars(select(m.IPObservation).where(m.IPObservation.address_id.in_(ids))):
        result[obs.address_id].append(obs)
    return result


def enrich(db, rows, *, details=True):
    grouped = observations(db, rows)
    sites = {s.id: s.name for s in db.scalars(select(m.Site))}
    prefixes = {p.id: p for p in db.scalars(select(m.Prefix))}
    result = []
    from .connections import identity_rank

    context = connection_context(db, [r for r in rows if not virtual_connections(grouped[r.id])], grouped)
    vlans = {v.id: v for v in db.scalars(select(m.VLAN))}
    for row in rows:
        item = serialize(row)
        item["managed"] = {k: item[k] for k in ("hostname", "operating_system", "location", "cabinet")}
        obs = sorted(grouped[row.id], key=lambda o: o.observed_at, reverse=True)
        if details:
            item["observations"] = [serialize(o) for o in obs]
        recent = [
            o for o in obs if o.observed_at >= now() - timedelta(hours=24) and o.data.get("present", True)
        ]
        ordered = sorted(recent, key=lambda o: identity_rank(o, context["devices"]))
        for field in (
            "hostname",
            "operating_system",
            "mac_address",
            "power_state",
            "reachability",
            "network",
            "vm_host",
            "dvport",
            "dvswitch",
        ):
            if not item.get(field):
                item[field] = next(
                    (
                        o.data[field]
                        for o in (recent if field == "reachability" else ordered)
                        if o.data.get(field)
                    ),
                    "",
                )
        macs = identity_macs(recent, context["devices"])
        all_macs = {normalized_mac(o.data.get("mac_address")) for o in recent} - {""}
        item["mac_conflict"] = len(all_macs) > 1
        if len(macs) > 1:
            item["mac_address"] = " / ".join(sorted(macs))
        item["location"] = (
            sites.get(row.sub_site_id or row.site_id)
            or item["location"]
            or sites.get(prefixes[row.prefix_id].site_id, "")
        )
        item["last_observed_at"] = obs[0].observed_at.isoformat() if obs else None
        item["stale"] = bool(obs and not recent)
        item["sources"] = sorted({o.source for o in obs})
        virtual = virtual_connections(obs)
        connections = [] if virtual else connection_candidates(db, row, context=context, obs=obs)
        if details:
            item["connections"] = connections
        physical = physical_connections(connections)
        item.update(connected_device="", connected_port="", connection_type="", connection_ambiguous=False)
        if virtual:
            item["connection_type"] = "vcenter"
            item["connection_ambiguous"] = len(virtual) != 1
            item["network"] = ""
            if len(virtual) == 1:
                vm = virtual[0]
                item.update(
                    connected_device=vm["switch_name"] or "VMware",
                    connected_port=vm["dvport"],
                    network=vm["network"],
                )
        elif len(physical) == 1:
            port = physical[0]
            item.update(
                connected_device=port["device_name"],
                connected_port=port["interface_name"],
                connection_type="routed" if port.get("routed") else "physical",
                connection_members=port.get("members", []),
            )
            if not row.hostname and port.get("endpoint_name"):
                host_rank = min(
                    (identity_rank(o, context["devices"]) for o in ordered if o.data.get("hostname")),
                    default=99,
                )
                if port["priority"] <= host_rank:
                    item["hostname"] = port["endpoint_name"]
            if not item.get("device_id"):
                item["device_id"] = port["device_id"]
        else:
            item["connection_ambiguous"] = bool(connections)
        item["address_locked"] = bool(obs)
        vlan = vlans.get(prefixes[row.prefix_id].vlan_id)
        item["vlan"] = f"VLAN-{vlan.vid} / {vlan.name}" if vlan else ""
        item["cidr"] = prefixes[row.prefix_id].cidr
        item["availability"] = ping_availability(obs)
        result.append(item)
    return result


def virtual_connections(obs):
    """Keep each VM/NIC backing together; never mix fields from unrelated guests."""
    found = {}
    for o in sorted(obs, key=lambda o: o.observed_at, reverse=True):
        d = o.data
        if o.source != "vcenter" or o.observed_at < now() - timedelta(hours=24) or not d.get("present", True):
            continue
        if not (d.get("vm_id") or d.get("dvport") or d.get("dvswitch")):
            continue
        key = (d.get("integration_id", o.source_key), d.get("vm_id"), d.get("nic_key"))
        if key not in found:
            found[key] = {
                "integration_id": d.get("integration_id"),
                "vm_id": d.get("vm_id", ""),
                "nic_key": d.get("nic_key", ""),
                "switch_name": d.get("dvswitch_name") or d.get("vswitch_name") or "",
                "network": d.get("network", ""),
                "dvport": d.get("dvport", ""),
            }
    return list(found.values())


def physical_connections(candidates):
    manual = [c for c in candidates if c["source"] == "manual"]
    return manual or [c for c in candidates if not c.get("uplink") and not c["ambiguous"]]


def prefix_metadata(db, prefix):
    vlan = db.get(m.VLAN, prefix.vlan_id) if prefix.vlan_id else None
    site = db.get(m.Site, prefix.site_id) if prefix.site_id else None
    return {
        "cidr": prefix.cidr,
        "vlan": f"VLAN-{vlan.vid} / {vlan.name}" if vlan else "",
        "location": site.name if site else "",
    }


def prefix_addresses(db, prefix, offset=0, limit=100, allocated=False, *, active_only=False, details=True):
    network = ipaddress.ip_network(prefix.cidr)
    if allocated or active_only:
        active = active_address_ids(db, {prefix.vrf_id}) if active_only else None
        rows = sorted(
            (
                r
                for r in db.scalars(select(m.IPAddress).where(m.IPAddress.vrf_id == prefix.vrf_id))
                if ipaddress.ip_address(r.address) in network and (active is None or r.id in active)
            ),
            key=lambda r: int(ipaddress.ip_address(r.address)),
        )
        return {
            "items": enrich(db, rows[offset : offset + limit], details=details),
            "total": str(len(rows)),
            "offset": str(offset),
        }
    stop = min(offset + limit, network.num_addresses)
    addresses = [str(network[i]) for i in range(offset, stop)]
    rows = db.scalars(
        select(m.IPAddress).where(m.IPAddress.vrf_id == prefix.vrf_id, m.IPAddress.address.in_(addresses))
    ).all()
    mapped = {r["address"]: r for r in enrich(db, rows, details=details)}
    metadata = prefix_metadata(db, prefix)
    items = []
    for address in addresses:
        reserved = (
            network.version == 4
            and network.prefixlen < 31
            and ipaddress.ip_address(address) in (network.network_address, network.broadcast_address)
        )
        items.append(
            mapped.get(
                address,
                {
                    **metadata,
                    "address": address,
                    "prefix_id": prefix.id,
                    "vrf_id": prefix.vrf_id,
                    "status": "network" if reserved else "unassigned",
                    "sources": [],
                },
            )
        )
    return {"items": items, "total": str(network.num_addresses), "offset": str(offset)}


def identity_macs(obs, devices):
    from .connections import identity_rank

    ranked = sorted(
        (
            o
            for o in obs
            if o.observed_at >= now() - timedelta(hours=24)
            and o.data.get("present", True)
            and normalized_mac(o.data.get("mac_address"))
        ),
        key=lambda o: identity_rank(o, devices),
    )
    if not ranked:
        return set()
    rank = identity_rank(ranked[0], devices)
    return {normalized_mac(o.data.get("mac_address")) for o in ranked if identity_rank(o, devices) == rank}


def connection_context(db, rows=None, grouped=None):
    from .connections import device_rank, latest_snapshots

    if rows is not None and not rows:
        return {"devices": {}, "ports": {}, "indexed": {}}
    stmt = select(m.Device).where(m.Device.archived.is_(False))
    if rows is not None:
        stmt = stmt.where(m.Device.vrf_id.in_({r.vrf_id for r in rows}))
    devices = {d.id: d for d in db.scalars(stmt)}
    wanted, addresses, manual = {}, set(), set()
    if rows is not None:
        grouped = grouped if grouped is not None else observations(db, rows)
        for row in rows:
            wanted.setdefault(row.vrf_id, set()).update(identity_macs(grouped[row.id], devices))
            addresses.add(row.address)
            if row.interface_id:
                manual.add(row.interface_id)
        if not any(wanted.values()) and not manual:
            return {"devices": devices, "ports": {}, "indexed": {}}
    snapshots = latest_snapshots(db, list(devices))
    facts, pairs = {}, set()
    for device_id, (snapshot, stamp) in snapshots.items():
        device = devices[device_id]
        macs = wanted.get(device.vrf_id, ()) if rows is not None else snapshot["macs"]
        for mac in macs:
            for index in snapshot["macs"].get(mac, ()):
                facts[(device_id, index, mac)] = {"source": "arp/ndp+fdb", "observed_at": stamp.isoformat()}
                pairs.add((device_id, index))
        if device_rank(device) == 4:
            for address, entries in snapshot["arp"].items():
                if rows is not None and address not in addresses:
                    continue
                for mac, index in entries:
                    if rows is not None and mac not in wanted.get(device.vrf_id, ()):
                        continue
                    item = facts.setdefault(
                        (device_id, index, mac),
                        {
                            "source": "firewall_arp",
                            "routed": True,
                            "observed_at": stamp.isoformat(),
                            "addresses": [],
                        },
                    )
                    if item.get("routed"):
                        item["addresses"].append(address)
                    pairs.add((device_id, index))
    clauses = []
    if pairs:
        clauses.append(tuple_(m.Interface.device_id, m.Interface.if_index).in_(pairs))
    if manual:
        clauses.append(m.Interface.id.in_(manual))
    # Legacy evidence/debug callers may need manually assigned ports absent from FDB.
    if rows is None:
        clauses = [m.Interface.device_id.in_(devices)]
    ports = (
        {
            p.id: p
            for p in db.scalars(select(m.Interface).where(m.Interface.is_deleted.is_(False), or_(*clauses)))
        }
        if clauses
        else {}
    )
    by_index = {(p.device_id, p.if_index): p for p in ports.values()}
    links = {}
    if ports:
        for link in db.scalars(
            select(m.Link).where(
                m.Link.is_current.is_(True), m.Link.device_id.in_({p.device_id for p in ports.values()})
            )
        ):
            peer = devices.get(link.manual_remote_device_id or link.remote_device_id)
            if (
                peer
                and (
                    peer.kind in ("switch", "router", "firewall")
                    or "switch" in peer.device_type.name.casefold()
                )
                and (
                    link.source == "manual"
                    or link.last_seen_at
                    and link.last_seen_at >= now() - timedelta(hours=24)
                )
            ):
                links.setdefault(link.device_id, set()).add(link.interface_name)
    indexed = {}
    for (device_id, index, mac), fact in facts.items():
        port = by_index.get((device_id, index))
        if not port:
            continue
        device = devices[device_id]
        snapshot = snapshots[device_id][0]
        uplink = port.name in snapshot["uplinks"] or port.name in links.get(device_id, ())
        indexed.setdefault((device.vrf_id, mac), {})[port.id] = {
            **fact,
            "interface_id": port.id,
            "confidence": 0.4 if uplink else 0.8,
            "ambiguous": uplink,
            "uplink": uplink,
            "direct_hosts": {
                address: info for (address, name), info in snapshot["hosts"].items() if name == port.name
            },
        }
    return {"devices": devices, "ports": ports, "indexed": indexed}


def connection_candidates(db, row, *, context=None, obs=None):
    from .connections import device_rank

    obs = obs if obs is not None else observations(db, [row])[row.id]
    context = context or connection_context(db, [row], {row.id: obs})
    macs = identity_macs(obs, context["devices"])
    candidates = {}
    for mac in macs:
        for id, candidate in context["indexed"].get((row.vrf_id, mac), {}).items():
            if candidate.get("routed") and row.address not in candidate.get("addresses", ()):
                continue
            item = dict(candidate)
            host = item.pop("direct_hosts", {}).get(row.address)
            if host:
                item.update(
                    uplink=False,
                    ambiguous=False,
                    confidence=0.95,
                    source="lldp/cdp+arp/fdb",
                    endpoint_name=host["name"],
                    members=host["members"],
                )
            candidates[id] = item
    if row.interface_id and row.interface_id in context["ports"]:
        candidates[row.interface_id] = dict(
            interface_id=row.interface_id, source="manual", confidence=1.0, ambiguous=False
        )
    found = []
    for item in candidates.values():
        port = context["ports"].get(item["interface_id"])
        device = context["devices"].get(port.device_id) if port else None
        if not device:
            continue
        item.update(
            interface_name=port.name,
            device_id=device.id,
            device_name=device.name,
            priority=device_rank(device),
        )
        found.append(item)
    eligible = [c for c in found if not c.get("uplink") and c["source"] != "manual"]
    priority = min((c["priority"] for c in eligible), default=99)
    access_count = sum(c["priority"] == priority for c in eligible)
    for item in found:
        if item["source"] != "manual" and (
            item.get("uplink") or item["priority"] != priority or access_count > 1 or len(macs) > 1
        ):
            item.update(ambiguous=True, confidence=0.4)
    return found


def inventory_observations(db, device, collected):
    from ..discovery.correlation import correlate

    prefixes = db.scalars(select(m.Prefix).where(m.Prefix.vrf_id == device.vrf_id)).all()
    entries = [{"ip": device.management_ip, "mac": "", "hostname": collected.get("hostname", "")}]
    entries += correlate(collected.get("tables", {}), collected.get("neighbors", []))
    for entry in entries:
        prefix = prefix_for(db, entry["ip"], prefixes)
        if prefix:
            observe(
                db,
                prefix,
                entry["ip"],
                "inventory",
                device.id,
                {
                    "mac_address": normalized_mac(entry.get("mac")),
                    "hostname": entry.get("hostname", ""),
                    "device_id": device.id,
                    "device_name": device.name,
                },
            )
