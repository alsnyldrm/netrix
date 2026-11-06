"""Reciprocal passive rear cabling; unresolved paths never become guessed links."""

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import BigInteger, String, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from .. import models as m
from ..services import get

ENDPOINT = ("device_id", "interface_id", "device_name", "port_name")
PATH = (
    "site_id",
    "floor_number",
    "department_name",
    "room_name",
    "cabinet_name",
    "panel_name",
    "port_number",
)
TARGET = (*PATH, "panel_unit", "port_id", *ENDPOINT)


def lock(db):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('patch-cabling', 0))"))
        return
    # One short DB mutex covers reciprocal writes and structural reconciliation.
    # A real increment also participates in Galera write-set certification.
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.mysql import insert
    statement = insert(m.SystemState).values(key="patch-cabling", value="1")
    version = cast(cast(m.SystemState.value, BigInteger) + 1, String(100))
    if db.get_bind().dialect.name == "sqlite":
        statement = statement.on_conflict_do_update(index_elements=["key"], set_={"value": version})
    else:
        statement = statement.on_duplicate_key_update(value=version)
    db.execute(statement)


def endpoint(db, payload):
    device = get(db, m.Device, payload.device_id) if payload.device_id else None
    if not device and payload.device_name:
        matches = list(
            db.scalars(
                select(m.Device)
                .where(
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    or_(
                        func.lower(m.Device.name) == payload.device_name.lower(),
                        m.Device.management_ip == payload.device_name,
                    ),
                )
                .limit(2)
            )
        )
        if len(matches) == 1:
            device = matches[0]
    if device and (device.archived or not device.discovery_scope_id):
        raise HTTPException(422, "Aktif cihaz envanterinden bir cihaz seçin")
    interface = get(db, m.Interface, payload.interface_id) if payload.interface_id else None
    if interface and (not device or interface.device_id != device.id or interface.is_deleted):
        raise HTTPException(422, "Port seçilen cihaza ait ve aktif olmalı")
    if device and not interface and payload.port_name:
        interface = db.scalar(
            select(m.Interface)
            .where(
                m.Interface.device_id == device.id,
                m.Interface.is_deleted.is_(False),
                func.lower(m.Interface.name) == payload.port_name.lower(),
            )
            .limit(1)
        )
    if (interface or payload.port_name) and not (device or payload.device_name):
        raise HTTPException(422, "Port bilgisi için bağlı cihazı da girin")
    return dict(
        device_id=device.id if device else None,
        interface_id=interface.id if interface else None,
        device_name=device.name if device else payload.device_name,
        port_name=interface.name if interface else payload.port_name,
    )


def descriptions(db, *, ids=None, specs=None, current=False):
    room, site = aliased(m.Site), aliased(m.Site)
    stmt = (
        select(
            m.PatchPort,
            m.PatchPanel,
            m.Cabinet,
            room.floor_number,
            room.department_name,
            room.name,
            site.name,
            m.Institution.name,
            m.Device.name,
            m.Interface.name,
        )
        .join(m.PatchPanel, m.PatchPanel.id == m.PatchPort.panel_id)
        .join(m.Cabinet, m.Cabinet.id == m.PatchPanel.cabinet_id)
        .outerjoin(room, room.id == m.Cabinet.sub_site_id)
        .outerjoin(site, site.id == m.Cabinet.site_id)
        .outerjoin(m.Institution, m.Institution.id == site.institution_id)
        .outerjoin(m.Device, m.Device.id == m.PatchPort.device_id)
        .outerjoin(m.Interface, m.Interface.id == m.PatchPort.interface_id)
    )
    if specs is not None:
        clauses = [m.PatchPort.id.in_({s.get("port_id") for s in specs if s.get("port_id")})]
        complete = [s for s in specs if all(s.get(k) for k in PATH)]
        if complete:
            clauses.append(
                and_(
                    m.Cabinet.site_id.in_({s["site_id"] for s in complete}),
                    func.lower(m.Cabinet.name).in_({s["cabinet_name"].lower() for s in complete}),
                    func.lower(m.PatchPanel.name).in_({s["panel_name"].lower() for s in complete}),
                    func.lower(m.PatchPort.number).in_({s["port_number"].lower() for s in complete}),
                )
            )
        stmt = stmt.where(or_(*clauses))
    else:
        if not ids:
            return {}
        stmt = stmt.where(m.PatchPort.id.in_(ids))
    if current:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    result = {}
    for (
        port,
        panel,
        cabinet,
        floor,
        department,
        room_name,
        site_name,
        institution,
        device_name,
        interface_name,
    ) in db.execute(stmt):
        result[port.id] = (
            port,
            {
                "port_id": port.id,
                "site_id": cabinet.site_id,
                "site_name": site_name or "",
                "institution_name": institution or "",
                "floor_number": floor or "",
                "department_name": department or "",
                "room_name": room_name or "",
                "room_id": cabinet.sub_site_id,
                "cabinet_id": cabinet.id,
                "cabinet_name": cabinet.name,
                "panel_id": panel.id,
                "panel_name": panel.name,
                "panel_unit": panel.start_unit,
                "port_number": port.number,
                "kind": panel.kind,
                "device_id": port.device_id,
                "interface_id": port.interface_id,
                "device_name": device_name or port.device_name,
                "port_name": interface_name or port.port_name,
            },
        )
    return result


def normalized(value):
    return str(value or "").strip().casefold().replace("i\u0307", "i")


def matches(spec, catalog):
    if spec.get("port_id") in catalog:
        return [catalog[spec["port_id"]]]
    key = tuple(normalized(spec.get(k)) for k in PATH)
    return [
        (port, desc)
        for port, desc in catalog.values()
        if tuple(normalized(desc.get(k)) for k in PATH) == key
        and (not spec.get("panel_unit") or desc["panel_unit"] == spec["panel_unit"])
    ]


def detach(db, port):
    if port.peer_port_id:
        other = db.scalar(
            select(m.PatchPort)
            .where(m.PatchPort.id == port.peer_port_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if other and other.peer_port_id == port.id:
            other.peer_port_id, other.external_data = None, {}
    port.peer_port_id, port.external_data = None, {}
    db.flush()


def merged_endpoint(db, other, spec):
    from .schemas import PatchEndpointInput

    desired = endpoint(
        db,
        PatchEndpointInput.model_validate(
            {k: spec.get(k) or (None if k.endswith("_id") else "") for k in ENDPOINT}
        ),
    )
    current = {k: getattr(other, k) for k in ENDPOINT}
    for key, name in (("device_id", "device_name"), ("interface_id", "port_name")):
        if desired[key] and current[key]:
            conflict = desired[key] != current[key]
        else:
            conflict = bool(
                desired[name] and current[name] and normalized(desired[name]) != normalized(current[name])
            )
        if conflict:
            raise HTTPException(
                409, "Karşı portun iç bağlantısı farklı bir cihaza/porta ait; önce karşı portu düzenleyin"
            )
    return {k: desired[k] or current[k] for k in ENDPOINT}


def bind(db, port, other, spec):
    if port.id == other.id:
        raise HTTPException(422, "Bir patch portu kendisine bağlanamaz")
    own_panel, remote_panel = db.get(m.PatchPanel, port.panel_id), db.get(m.PatchPanel, other.panel_id)
    if own_panel.kind != remote_panel.kind:
        raise HTTPException(409, "CAT ve fiber patch portları birbirine bağlanamaz")
    if other.peer_port_id and other.peer_port_id != port.id:
        raise HTTPException(409, "Karşı portun dış bağlantısı başka bir portta kullanılıyor")
    if not other.peer_port_id and other.external_data:
        source = descriptions(db, ids={port.id}, current=True)
        if not matches(other.external_data, source):
            raise HTTPException(
                409, "Karşı portun bekleyen bir dış bağlantısı var; önce bu bağlantıyı düzenleyin"
            )
    values = merged_endpoint(db, other, spec)
    if port.peer_port_id and port.peer_port_id != other.id:
        detach(db, port)
    for key, value in values.items():
        setattr(other, key, value)
    db.flush()
    catalog = descriptions(db, ids={port.id, other.id}, current=True)
    port.peer_port_id, other.peer_port_id = other.id, port.id
    port.external_data = catalog[other.id][1]
    other.external_data = catalog[port.id][1]
    db.flush()


def update_external(db, port, spec):
    if spec is None:
        detach(db, port)
        return
    data = spec.model_dump(exclude_none=True)
    if data.get("site_id"):
        site = get(db, m.Site, data["site_id"])
        if site.parent_id:
            raise HTTPException(422, "Karşı uç lokasyonu ana lokasyon olmalı")
    catalog = descriptions(db, specs=[data], current=True)
    candidates = matches(data, catalog)
    if len(candidates) == 1:
        bind(db, port, candidates[0][0], data)
    else:
        if not all(data.get(k) for k in PATH):
            raise HTTPException(422, "Karşı port artık yok; bekleyen bağlantı için tam konumunu girin")
        detach(db, port)
        # Validate even a pending manual endpoint without creating inventory.
        from .schemas import PatchEndpointInput

        data.update(
            endpoint(db, PatchEndpointInput.model_validate({k: data.get(k) for k in ENDPOINT if k in data}))
        )
        port.external_data = {**data, "_status": "ambiguous" if candidates else "pending"}
        db.flush()


def reconcile(db):
    pending = list(
        db.scalars(
            select(m.PatchPort)
            .where(m.PatchPort.peer_port_id.is_(None), m.PatchPort.external_data != {})
            .order_by(m.PatchPort.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if not pending:
        return
    catalog = descriptions(db, specs=[p.external_data for p in pending], current=True)
    claims = defaultdict(list)
    for port in pending:
        found = matches(port.external_data, catalog)
        if len(found) == 1:
            claims[found[0][0].id].append(port)
        else:
            port.external_data = {**port.external_data, "_status": "ambiguous" if found else "pending"}
    for target_id, sources in claims.items():
        if len(sources) > 1:
            for port in sources:
                port.external_data = {**port.external_data, "_status": "ambiguous"}
            continue
        port, other = sources[0], catalog[target_id][0]
        if port.peer_port_id:
            continue
        try:
            bind(db, port, other, port.external_data)
        except HTTPException as exc:
            if exc.status_code not in (409, 422):
                raise
            port.external_data = {**port.external_data, "_status": "conflict"}
    db.flush()


def refresh_pair(db, port):
    if port.peer_port_id:
        data = descriptions(db, ids={port.id, port.peer_port_id}, current=True)
        if len(data) == 2:
            other = data[port.peer_port_id][0]
            port.external_data, other.external_data = data[other.id][1], data[port.id][1]


def enrich(db, items):
    peers = descriptions(db, ids={i["peer_port_id"] for i in items if i.get("peer_port_id")})
    for item in items:
        saved = item.pop("external_data", {}) or {}
        peer = peers.get(item.get("peer_port_id"))
        item["external"] = (
            peer[1] if peer else ({k: v for k, v in saved.items() if not k.startswith("_")} or None)
        )
        item["external_status"] = "connected" if peer else saved.get("_status", "pending" if saved else "")
    return items


def before_delete(db, port_ids):
    deleted = descriptions(db, ids=set(port_ids), current=True)
    peers = descriptions(
        db, ids={p.peer_port_id for p, _ in deleted.values() if p.peer_port_id} - set(port_ids), current=True
    )
    for port, desc in deleted.values():
        if port.peer_port_id in peers:
            other = peers[port.peer_port_id][0]
            other.peer_port_id = None
            other.external_data = {**desc, "_status": "pending"}
        port.peer_port_id = None
    db.flush()
