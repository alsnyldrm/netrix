"""SQL-only vacant address selection and VLAN-scoped manual assignment."""

import ipaddress
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from .. import services as svc
from ..core import now
from .service import ping_availability


def bounds(vlan):
    if not vlan.cidr:
        raise HTTPException(422, "Önce VLAN için bir IP bloğu tanımlayın")
    network = ipaddress.ip_network(vlan.cidr)
    trim = network.version == 4 and network.prefixlen < 31
    return network, int(trim), network.num_addresses - int(trim)


def occupancy(db, vlan):
    rows = list(db.scalars(select(m.IPAddress).where(m.IPAddress.vlan_id == vlan.id)))
    latest = {}
    for observation in db.scalars(
        select(m.IPObservation)
        .join(m.IPAddress, m.IPAddress.id == m.IPObservation.address_id)
        .where(
            m.IPAddress.vlan_id == vlan.id,
            m.IPObservation.source == "icmp",
            m.IPObservation.observed_at >= now() - timedelta(hours=24),
        )
        .order_by(m.IPObservation.observed_at.desc(), m.IPObservation.id.desc())
    ):
        latest.setdefault(observation.address_id, observation.data)
    blocked = {
        r.address
        for r in rows
        if r.status == "reserved"
        or r.is_gateway
        or (
            latest.get(r.id, {}).get("present", True)
            and latest.get(r.id, {}).get("reachability") == "reachable"
        )
    }
    return {r.address: r for r in rows}, blocked


def available(db, vlan, *, offset=0, limit=100, q=""):
    network, first, stop = bounds(vlan)
    _, blocked = occupancy(db, vlan)
    q = q.strip().lower()
    if q:
        try:
            exact = ipaddress.ip_address(q)
        except ValueError:
            exact = None
        if exact:
            usable = exact in network and first <= int(exact) - int(network.network_address) < stop
            return {
                "items": [{"address": str(exact)}] if usable and str(exact) not in blocked else [],
                "next_offset": None,
            }
    cursor = max(first, offset)
    items = []
    # IPv4 scopes are capped at /16. Never enumerate a whole IPv6 network.
    end = min(stop, cursor + (65536 if network.version == 4 else 4096))
    while cursor < end and len(items) < limit:
        address = str(network[cursor])
        cursor += 1
        if address not in blocked and (not q or address.startswith(q)):
            items.append({"address": address})
    return {"items": items, "next_offset": str(cursor) if cursor < stop else None}


def inspection(db, vlan, *, offset=0, limit=256, address=""):
    network, first, stop = bounds(vlan)
    cursor = max(first, offset)
    if address:
        try:
            target = ipaddress.ip_address(address.strip())
            index = int(target) - int(network.network_address)
            if target not in network or not first <= index < stop:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Bu VLAN içinde kullanılabilir bir IP adresi girin") from None
        cursor = first + ((index - first) // limit) * limit
    if cursor >= stop:
        raise HTTPException(422, "Adres başlangıcı VLAN dışında")
    rows, blocked = occupancy(db, vlan)
    items = []
    for index in range(cursor, min(cursor + limit, stop)):
        ip = str(network[index])
        row = rows.get(ip)
        items.append(
            {"address": ip, "id": row.id if row else None, "state": "occupied" if ip in blocked else "free"}
        )
    used = sum(i["state"] == "occupied" for i in items)
    return {
        "items": items,
        "capacity": str(stop - first),
        "offset": str(cursor),
        "next_offset": str(cursor + limit) if cursor + limit < stop else None,
        "previous_offset": str(max(first, cursor - limit)) if cursor > first else None,
        "occupied": used,
        "free": len(items) - used,
    }


def assign(db, vlan, payload, user):
    network, first, stop = bounds(vlan)
    address = ipaddress.ip_address(payload.address)
    if payload.vlan_id != vlan.id or payload.vrf_id != vlan.vrf_id or address not in network:
        raise HTTPException(422, "IP adresi açık olan VLAN ve VRF içinde olmalı")
    if not first <= int(address) - int(network.network_address) < stop:
        raise HTTPException(422, "Ağ/yayın adresi atanamaz")
    svc.lock_vrf(db, vlan.vrf_id)
    row = db.scalar(
        select(m.IPAddress)
        .where(
            m.IPAddress.vrf_id == vlan.vrf_id,
            m.IPAddress.address == str(address),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row:
        if row.vlan_id != vlan.id:
            raise HTTPException(409, "Bu IP başka bir VLAN kaydına bağlı")
        latest = db.scalar(
            select(m.IPObservation)
            .where(
                m.IPObservation.address_id == row.id,
                m.IPObservation.source == "icmp",
            )
            .order_by(m.IPObservation.observed_at.desc(), m.IPObservation.id.desc())
            .limit(1)
            .with_for_update(of=m.IPObservation)
        )
        if (
            row.status == "reserved"
            or row.is_gateway
            or ping_availability([latest] if latest else []) == "active"
        ):
            raise HTTPException(409, "Seçilen IP artık boş değil. Boş IP listesinden başka bir adres seçin.")
    # Reuse inactive discovery rows: retain their observations, source result and identity.
    saved = svc.save_resource(db, "addresses", payload.model_dump(), user, row.id if row else None)
    svc.publish(ipam_vlan=vlan.id)
    return saved
