"""Maintain current links from completed protocol snapshots without losing history."""

from sqlalchemy import select

from .. import models as m
from ..core import now
from .link_deletions import matches as excluded_match
from .link_deletions import reconcile_exclusions, user_managed
from .neighbor_detail import addresses, same_neighbor
from .neighbor_labels import neighbor_label


def legacy_match(link, neighbor):
    if same_neighbor({"interface_name": link.interface_name, "evidence": link.evidence or {}}, neighbor):
        return True
    evidence = neighbor.get("evidence", {})
    lldp, cdp = evidence.get("lldp", {}), evidence.get("cdp", {})
    if link.source == "lldp" and lldp:
        aliases = {neighbor["interface_name"], lldp.get("local_port_id"), lldp.get("local_port_number")}
        return (
            link.interface_name in aliases
            and neighbor_label(link.remote_port) == lldp.get("port_id")
            and neighbor_label(link.remote_name) in (lldp.get("system_name"), lldp.get("chassis_id"))
        )
    if link.source == "cdp" and cdp and link.interface_name == neighbor["interface_name"]:
        try:
            raw_hex = link.remote_name.encode("latin1").hex()
        except UnicodeEncodeError:
            raw_hex = None
        return neighbor_label(link.remote_port) == cdp.get("port_id") and (
            (raw_hex is not None and raw_hex == cdp.get("device_id_hex"))
            or neighbor_label(link.remote_name) in (cdp.get("device_id"), cdp.get("system_name"))
        )
    # Compatibility with collectors that have no structured evidence yet.
    return (
        link.source == neighbor["source"]
        and link.interface_name == neighbor["interface_name"]
        and neighbor_label(link.remote_name) == neighbor["remote_name"]
        and neighbor_label(link.remote_port) == neighbor["remote_port"]
    )


def sync_links(db, device, collected):
    if device.discovery_scope_id is None or device.archived:
        return
    links = list(
        db.scalars(
            select(m.Link)
            .where(m.Link.device_id == device.id)
            .order_by(m.Link.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    reconcile_exclusions(db, links)
    seen = set()
    for neighbor in collected.get("neighbors", []):
        if any(link.auto_add_excluded and excluded_match(link, neighbor, db) for link in links):
            # Suppression also applies to protocol duplicates in partial snapshots.
            for link in links:
                if excluded_match(link, neighbor, db):
                    if user_managed(link):
                        if link.is_current:
                            seen.add(link.id)
                            link.updated_at = link.last_seen_at = now()
                        continue
                    link.auto_add_excluded = True
                    link.is_current = False
            continue
        fields = {key: neighbor[key] for key in ("interface_name", "remote_name", "remote_port")}
        link = next((l for l in links if all(getattr(l, k) == v for k, v in fields.items())), None)
        if link and link.source == "manual":
            seen.add(link.id)
            continue
        if not link:
            candidates = [
                l for l in links if l.source != "manual" and l.id not in seen and legacy_match(l, neighbor)
            ]
            # When joining LLDP and CDP, preserve one ID and retire the duplicate.
            link = next(
                (
                    l
                    for l in candidates
                    if l.manual_remote_name is not None or l.manual_remote_port is not None
                ),
                None,
            ) or next((l for l in candidates if l.source == "cdp"), candidates[0] if candidates else None)
        if not link:
            link = m.Link(device_id=device.id, **fields, source=neighbor["source"])
            db.add(link)
            links.append(link)
            db.add(
                m.Event(
                    device_id=device.id,
                    kind="link_observed",
                    message=f"{device.name}: {neighbor['source'].upper()} komşusu gözlemlendi",
                    details={"remote_name": neighbor["remote_name"]},
                )
            )
        for key, value in fields.items():
            setattr(link, key, value)
        link.source = neighbor["source"]
        link.evidence = neighbor.get("evidence", {})
        link.is_current = True
        link.updated_at = link.last_seen_at = now()
        # Advertised names are candidates, not proof of managed-device identity.
        advertised_addresses = addresses(neighbor)
        candidates = list(
            db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id == device.vrf_id,
                    m.Device.id != device.id,
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    (
                        m.Device.management_ip.in_(advertised_addresses)
                        if advertised_addresses
                        else m.Device.name == neighbor["remote_name"]
                    ),
                )
            )
        )
        link.confidence = (0.9 if advertised_addresses else 0.65) if len(candidates) == 1 else 0.5
        link.remote_device_id = candidates[0].id if len(candidates) == 1 else None
        db.flush()
        seen.add(link.id)
    complete = set(collected.get("neighbor_protocols_complete", []))
    for link in links:
        # A failed, partial or unsupported walk cannot prove a neighbor disappeared.
        if (
            link.id not in seen
            and link.source != "manual"
            and set(link.source.split("+")) <= complete
            and link.is_current
        ):
            link.is_current = False
            db.add(
                m.Event(
                    device_id=device.id,
                    kind="link_not_observed",
                    message=f"{device.name}: komşu güncel protokol tablosunda görülmedi",
                    details={
                        "link_id": link.id,
                        "last_seen_at": (link.last_seen_at or link.updated_at).isoformat(),
                    },
                )
            )


def repair_stored_ports(db):
    """Repair current labels using already stored evidence, without fabricating a new observation."""
    from .neighbor_detail import remote_port

    rows = list(db.scalars(select(m.Link).order_by(m.Link.id).with_for_update()))
    by_key = {(r.device_id, r.interface_name, r.remote_name, r.remote_port): r for r in rows}
    changed = retired = 0
    for row in rows:
        if row.source == "manual" or not row.is_current or not row.evidence:
            continue
        port = remote_port(row.evidence, row.remote_port)[:120]
        if port == row.remote_port:
            continue
        key = (row.device_id, row.interface_name, row.remote_name, port)
        existing = by_key.get(key)
        if existing:
            # The corrected record already exists; preserve the historical raw row.
            # Only a fresh observation may reactivate the other record.
            if existing.is_current:
                row.is_current = False
                retired += 1
            continue
        del by_key[(row.device_id, row.interface_name, row.remote_name, row.remote_port)]
        row.remote_port = port
        by_key[key] = row
        changed += 1
    db.flush()
    return {"corrected_ports": changed, "retired_duplicates": retired}
