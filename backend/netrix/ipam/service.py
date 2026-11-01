"""VLAN IPAM policies and DHCP/VMware source observations."""

import ipaddress
import json
import re
from datetime import timedelta
from types import SimpleNamespace

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


def save_settings(db, vlan_id, payload, user):
    vlan = get(db, m.VLAN, vlan_id)
    data = payload.model_dump()
    if payload.dns_server_id:
        get(db, m.DNSServer, payload.dns_server_id)
    for key, value in data.items():
        setattr(vlan, key, value)
    audit(db, user, "ipam_settings", "vlans", vlan.id, "VLAN ayarları güncellendi")
    db.commit()
    publish()
    return vlan_summary(db, vlan)


def scan_boundary(db, vlan):
    if not vlan.cidr:
        raise HTTPException(422, "VLAN için IP bloğu tanımlayın")
    return SimpleNamespace(enabled=True, cidr=vlan.cidr, vrf_id=vlan.vrf_id, exclusions=[], seeds=[])


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


def vlan_summaries(db, prefixes):
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
    result = []
    for prefix in prefixes:
        if not prefix.cidr:
            item = serialize(prefix)
            item.update(
                capacity="0",
                used=0,
                utilization=0,
                vlan=f"VLAN-{prefix.vid} / {prefix.name}",
                display_name=f"VLAN-{prefix.vid} / {prefix.name}",
            )
            result.append(item)
            continue
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
        vlan = prefix
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


def vlan_summary(db, prefix):
    return vlan_summaries(db, [prefix])[0]


def targets(db, prefix, discover=False):
    scope = scan_boundary(db, prefix)
    network = ipaddress.ip_network(prefix.cidr)
    if discover:
        if network.version == 6:
            candidates = db.scalars(select(m.IPAddress.address).where(m.IPAddress.vlan_id == prefix.id)).all()
        else:
            candidates = map(str, network.hosts())
    else:
        candidates = db.scalars(select(m.IPAddress.address).where(m.IPAddress.vlan_id == prefix.id)).all()
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
    changed_target = id and (row.host != payload.host or row.port != payload.port or row.kind != payload.kind)
    if changed_target:
        row.last_success_at = None
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


def vlan_for(db, address, prefixes):
    ip = ipaddress.ip_address(address)
    eligible = [p for p in prefixes if p.cidr and ip in ipaddress.ip_network(p.cidr)]
    if len({p.vrf_id for p in eligible}) > 1:
        return None  # A source without VRF evidence cannot disambiguate duplicate IP spaces.
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
    # A collector may have read the prefix before the operator deleted it.
    # A locking read observes the current row even under MariaDB REPEATABLE READ.
    if not db.scalar(select(m.VLAN.id).where(m.VLAN.id == prefix.id).with_for_update()):
        return None
    row = db.scalar(
        select(m.IPAddress).where(m.IPAddress.vrf_id == prefix.vrf_id, m.IPAddress.address == str(ip))
    )
    if not row and not create:
        return None
    if not row:
        row = m.IPAddress(
            address=str(ip),
            vrf_id=prefix.vrf_id,
            vlan_id=prefix.id,
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


def enrich(db, rows, *, details=True, include_options=False):
    from .racks import address_cabinets

    if not rows:
        return []
    grouped = observations(db, rows)
    cabinets = address_cabinets(db, rows)
    sites = dict(db.execute(select(m.Site.id, m.Site.name)).all())
    prefixes = {p.id: p for p in db.scalars(select(m.VLAN).where(m.VLAN.id.in_({r.vlan_id for r in rows})))}
    result = []

    for row in rows:
        item = serialize(row)
        item["managed"] = {k: item[k] for k in ("hostname", "operating_system", "location", "cabinet")}
        item["cabinet"] = item["cabinet"] or cabinets.get(row.id, "")
        obs = sorted(grouped[row.id], key=lambda o: o.observed_at, reverse=True)
        if details:
            item["observations"] = [serialize(o) for o in obs]
        recent = [
            o for o in obs if o.observed_at >= now() - timedelta(hours=24) and o.data.get("present", True)
        ]
        ordered = sorted(recent, key=identity_rank)
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
        dns_name = next(
            (o.data.get("hostname") for o in recent if o.source == "dns" and o.data.get("hostname")), ""
        )
        if dns_name:
            item["hostname"] = dns_name
        macs = identity_macs(recent)
        all_macs = {normalized_mac(o.data.get("mac_address")) for o in recent} - {""}
        item["mac_conflict"] = len(all_macs) > 1
        if len(macs) > 1:
            item["mac_address"] = " / ".join(sorted(macs))
        item["location"] = (
            sites.get(row.sub_site_id or row.site_id)
            or item["location"]
            or sites.get(prefixes[row.vlan_id].site_id, "")
        )
        item["last_observed_at"] = obs[0].observed_at.isoformat() if obs else None
        item["stale"] = bool(obs and not recent)
        item["sources"] = sorted({o.source for o in obs})
        virtual = virtual_connections(obs)
        if include_options:
            from .jobs import connection_options

            item.update(connection_options(db, row, obs=obs))
        if details:
            item["connections"] = []
        item.update(
            connected_device="",
            connected_port="",
            connection_groups=[],
            connection_type="",
            connection_ambiguous=False,
        )
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
        item["address_locked"] = bool(obs)
        vlan = prefixes[row.vlan_id]
        item["vlan"] = f"VLAN-{vlan.vid} / {vlan.name}" if vlan else ""
        item["cidr"] = prefixes[row.vlan_id].cidr
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


def vlan_metadata(db, prefix):
    vlan = prefix
    site = db.get(m.Site, prefix.site_id) if prefix.site_id else None
    return {
        "cidr": prefix.cidr,
        "vlan": f"VLAN-{vlan.vid} / {vlan.name}" if vlan else "",
        "location": site.name if site else "",
    }


def vlan_addresses(db, prefix, offset=0, limit=100, allocated=False, *, active_only=False, details=True):
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
    metadata = vlan_metadata(db, prefix)
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
                    "vlan_id": prefix.id,
                    "vrf_id": prefix.vrf_id,
                    "status": "network" if reserved else "unassigned",
                    "sources": [],
                },
            )
        )
    return {"items": items, "total": str(network.num_addresses), "offset": str(offset)}


def identity_rank(observation):
    return {"dns": -1, "vcenter": 0, "windows_dhcp": 1}.get(observation.source, 6)


def identity_macs(obs):
    ranked = sorted(
        (
            o
            for o in obs
            if o.observed_at >= now() - timedelta(hours=24)
            and o.data.get("present", True)
            and normalized_mac(o.data.get("mac_address"))
        ),
        key=identity_rank,
    )
    if not ranked:
        return set()
    rank = identity_rank(ranked[0])
    return {normalized_mac(o.data.get("mac_address")) for o in ranked if identity_rank(o) == rank}
