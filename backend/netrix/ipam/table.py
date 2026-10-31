"""IPAM search before pagination and atomic bulk metadata changes."""

import ipaddress
import json

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..identity.security import audit
from . import service

COLUMNS = {
    "address": "IP adresi",
    "hostname": "Hostname",
    "mac_address": "MAC adresi",
    "connected_device": "Bağlı cihaz",
    "connected_port": "Port",
    "vlan": "VLAN",
    "operating_system": "İşletim sistemi",
    "cabinet": "Kabinet no",
    "location": "Lokasyon",
    "availability": "Durum",
    "status": "Atama durumu",
    "sources": "Kaynak",
    "cidr": "Ağ bloğu",
    "power_state": "Güç durumu",
    "vm_host": "VMware host",
    "network": "Port grubu / Sanal ağ",
}
LABELS = {
    "active": "Aktif",
    "passive": "Pasif",
    "unknown": "Bilinmiyor",
    "reserved": "Rezerve",
    "deprecated": "Kullanım dışı",
    "unassigned": "Atanmamış",
    "network": "Ağ / yayın",
    "inventory": "Envanter",
    "icmp": "Ping",
    "dns": "DNS",
    "vcenter": "VMware vCenter",
    "windows_dhcp": "Windows DHCP",
}


def normalized(value):
    return str(value or "").replace("İ", "i").replace("ı", "i").casefold()


def cell(row, key):
    value = row.get(key, "")
    if isinstance(value, list):
        value = " ".join(LABELS.get(v, v) for v in value)
    return normalized(LABELS.get(str(value), value))


def rules_from(raw):
    try:
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) > 20:
            raise ValueError()
        for r in values:
            if not isinstance(r, dict):
                raise ValueError()
            if (
                set(r) - {"field", "op", "value", "join"}
                or r.get("field") not in COLUMNS
                or r.get("op") not in ("contains", "not_contains", "eq", "ne", "gt", "lt")
                or r.get("join", "and") not in ("and", "or")
                or not isinstance(r.get("value"), str)
                or len(r["value"]) > 200
            ):
                raise ValueError()
        return values
    except (ValueError, TypeError):
        raise HTTPException(422, "Geçersiz IPAM filtreleri") from None


def matches(row, q, rules):
    # Every word can occur in any visible or hidden data column.
    haystack = " ".join(cell(row, key) for key in COLUMNS)
    if not all(word in haystack for word in normalized(q).split()):
        return False
    result = None
    for r in rules:
        left, right = cell(row, r["field"]), normalized(r["value"])
        op = r["op"]
        if op in ("gt", "lt"):
            try:
                a, b = (
                    (int(ipaddress.ip_address(v)) for v in (left, right))
                    if r["field"] == "address"
                    else (float(left), float(right))
                )
                current = a > b if op == "gt" else a < b
            except ValueError:
                current = False
        else:
            current = {
                "contains": right in left,
                "not_contains": right not in left,
                "eq": left == right,
                "ne": left != right,
            }[op]
        result = (
            current
            if result is None
            else (result or current if r.get("join") == "or" else result and current)
        )
    return result is not False


def addresses(db, prefix=None, *, offset=0, limit=100, allocated=False, q="", filters="[]"):
    rules = rules_from(filters)
    if prefix and not q and not rules:
        result = service.prefix_addresses(db, prefix, offset, limit, allocated)
    else:
        stmt = select(m.IPAddress)
        if prefix:
            network = ipaddress.ip_network(prefix.cidr)
            stmt = stmt.where(m.IPAddress.vrf_id == prefix.vrf_id)
        rows = db.scalars(stmt).all()
        if prefix:
            rows = [r for r in rows if ipaddress.ip_address(r.address) in network]
        enriched = service.enrich(db, rows)
        registered_only = False
        if prefix and not allocated:
            if network.num_addresses <= 65536:
                by_ip = {r["address"]: r for r in enriched}
                metadata = service.prefix_metadata(db, prefix)
                enriched = [
                    by_ip.get(
                        str(ip),
                        {
                            **metadata,
                            "address": str(ip),
                            "prefix_id": prefix.id,
                            "vrf_id": prefix.vrf_id,
                            "cidr": prefix.cidr,
                            "status": "network"
                            if network.version == 4
                            and network.prefixlen < 31
                            and ip in (network.network_address, network.broadcast_address)
                            else "unassigned",
                        },
                    )
                    for ip in network
                ]
            else:
                # Never enumerate an IPv6 space; registered data remains fully searchable.
                registered_only = True
        selected = sorted(
            (r for r in enriched if matches(r, q, rules)),
            key=lambda r: (
                ipaddress.ip_address(r["address"]).version,
                int(ipaddress.ip_address(r["address"])),
            ),
        )
        result = {
            "items": selected[offset : offset + limit],
            "total": str(len(selected)),
            "offset": str(offset),
            "registered_search": registered_only,
        }
    result["columns"] = [{"key": k, "label": v} for k, v in COLUMNS.items()]
    if prefix:
        result["prefix"] = service.prefix_summary(db, prefix)
    return result


def bulk(db, payload, user):
    ids = list(dict.fromkeys(payload.ids))
    rows = db.scalars(
        select(m.IPAddress)
        .where(m.IPAddress.id.in_(ids))
        .order_by(m.IPAddress.vrf_id, m.IPAddress.id)
        .with_for_update()
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "Seçilen IP kayıtlarından biri artık yok; listeyi yenileyin")
    if payload.action == "delete":
        if user.role != "admin":
            raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
        for row in rows:
            if db.scalar(
                select(m.Job.id).where(m.Job.target_id == row.id, m.Job.active_key.is_not(None)).limit(1)
            ):
                raise HTTPException(409, "Önce seçilen IP için çalışan izlemeyi durdurun")
        for row in rows:
            audit(db, user, "delete", "addresses", row.id, f"IP kaydı silindi: {row.address}")
            db.delete(row)
    else:
        allowed = set(s.IPInput.model_fields) - {"address"}
        if not payload.changes or set(payload.changes) - allowed:
            raise HTTPException(422, "IP ve MAC değiştirilemez; düzenlenecek alanları seçin")
        for row in rows:
            data = {k: getattr(row, k) for k in s.IPInput.model_fields}
            data.update(payload.changes)
            svc.save_resource(db, "addresses", data, user, row.id, commit=False)
    db.commit()
    svc.publish()
    return {"affected": len(rows)}
