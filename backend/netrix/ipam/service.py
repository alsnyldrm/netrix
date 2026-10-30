"""IPAM policies, source observations and cross-device endpoint correlation."""

import ipaddress
import json
import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

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
    if payload.ping_enabled or payload.discovery_enabled:
        require_scope(db, prefix, payload.scope_id)
    for key, value in data.items():
        setattr(prefix, key, value)
    audit(db, user, "ipam_settings", "prefixes", prefix.id, "Ağ bloğu ayarları güncellendi")
    db.commit()
    publish()
    return serialize(prefix)


def require_scope(db, prefix, scope_id=None):
    scope = db.get(m.Scope, scope_id or prefix.scope_id) if scope_id or prefix.scope_id else None
    network = ipaddress.ip_network(prefix.cidr)
    if not scope or not scope.enabled or scope.vrf_id != prefix.vrf_id:
        raise HTTPException(422, "Etkin ve yetkili keşif kapsamı seçin")
    allowed = ipaddress.ip_network(scope.cidr)
    if network.version != allowed.version or not network.subnet_of(allowed):
        raise HTTPException(422, "Ağ bloğu yetkili kapsamın dışında")
    return scope


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
            status="reserved" if source == "windows_dhcp" else "active",
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


def enrich(db, rows):
    grouped = observations(db, rows)
    sites = {s.id: s.name for s in db.scalars(select(m.Site))}
    prefixes = {p.id: p for p in db.scalars(select(m.Prefix))}
    result = []
    for row in rows:
        item = serialize(row)
        item["managed"] = {k: item[k] for k in ("hostname", "operating_system", "location", "cabinet")}
        obs = sorted(grouped[row.id], key=lambda o: o.observed_at, reverse=True)
        item["observations"] = [serialize(o) for o in obs]
        recent = [o for o in obs if o.observed_at >= now() - timedelta(hours=24)]
        for field in (
            "hostname",
            "operating_system",
            "mac_address",
            "power_state",
            "reachability",
            "network",
            "vm_host",
        ):
            if not item.get(field):
                item[field] = next((o.data[field] for o in recent if o.data.get(field)), "")
        macs = {normalized_mac(o.data.get("mac_address")) for o in recent} - {""}
        item["mac_conflict"] = len(macs) > 1
        if item["mac_conflict"]:
            item["mac_address"] = " / ".join(sorted(macs))
        item["location"] = item["location"] or sites.get(prefixes[row.prefix_id].site_id, "")
        item["last_observed_at"] = obs[0].observed_at.isoformat() if obs else None
        item["stale"] = bool(obs and not recent)
        item["sources"] = sorted({o.source for o in obs})
        result.append(item)
    return result


def prefix_addresses(db, prefix, offset=0, limit=100, allocated=False):
    network = ipaddress.ip_network(prefix.cidr)
    if allocated:
        rows = sorted(
            db.scalars(select(m.IPAddress).where(m.IPAddress.prefix_id == prefix.id)),
            key=lambda r: int(ipaddress.ip_address(r.address)),
        )
        return {
            "items": enrich(db, rows[offset : offset + limit]),
            "total": str(len(rows)),
            "offset": str(offset),
        }
    stop = min(offset + limit, network.num_addresses)
    addresses = [str(network[i]) for i in range(offset, stop)]
    rows = db.scalars(
        select(m.IPAddress).where(m.IPAddress.vrf_id == prefix.vrf_id, m.IPAddress.address.in_(addresses))
    ).all()
    mapped = {r["address"]: r for r in enrich(db, rows)}
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
                    "address": address,
                    "prefix_id": prefix.id,
                    "vrf_id": prefix.vrf_id,
                    "status": "network" if reserved else "unassigned",
                    "sources": [],
                },
            )
        )
    return {"items": items, "total": str(network.num_addresses), "offset": str(offset)}


def connection_candidates(db, row):
    """Correlate ARP on a gateway with FDB on *other* inventory switches."""
    obs = observations(db, [row])[row.id]
    macs = {
        normalized_mac(o.data.get("mac_address")) for o in obs if o.observed_at > now() - timedelta(hours=24)
    } - {""}
    candidates = {}
    if row.interface_id:
        port = db.get(m.Interface, row.interface_id)
        if port:
            candidates[port.id] = {
                "interface_id": port.id,
                "source": "manual",
                "confidence": 1.0,
                "ambiguous": False,
            }
    latest = {}
    for o in db.scalars(
        select(m.Observation)
        .join(m.Device, m.Observation.device_id == m.Device.id)
        .where(
            m.Device.vrf_id == row.vrf_id,
            m.Device.archived.is_(False),
            m.Observation.created_at >= now() - timedelta(hours=24),
        )
        .order_by(m.Observation.created_at.desc())
    ):
        if o.device_id not in latest and "tables" in o.evidence:
            latest[o.device_id] = o
    for device_id, o in latest.items():
        tables = o.evidence.get("tables", {})
        ports = {
            str(p.if_index): p
            for p in db.scalars(
                select(m.Interface).where(
                    m.Interface.device_id == device_id, m.Interface.is_deleted.is_(False)
                )
            )
        }
        uplinks = {n.get("interface_name") for n in o.evidence.get("neighbors", [])}
        for key in ("fdb_port", "vlan_fdb_port"):
            for index, bridge in tables.get(key, {}).items():
                try:
                    mac = ":".join(f"{int(v):02x}" for v in index.split(".")[-6:])
                except ValueError:
                    continue
                if mac not in macs:
                    continue
                port = ports.get(str(tables.get("bridge_ifindex", {}).get(str(bridge))))
                if port and port.id not in candidates:
                    uplink = port.name in uplinks
                    candidates[port.id] = {
                        "interface_id": port.id,
                        "source": "arp/ndp+fdb",
                        "confidence": 0.4 if uplink else 0.8,
                        "ambiguous": uplink,
                        "observed_at": o.created_at.isoformat(),
                        "uplink": uplink,
                    }
    found = list(candidates.values())
    for item in found:
        port = db.get(m.Interface, item["interface_id"])
        device = db.get(m.Device, port.device_id)
        item.update(interface_name=port.name, device_id=device.id, device_name=device.name)
        if item["source"] != "manual" and (len(found) > 1 or len(macs) > 1):
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
