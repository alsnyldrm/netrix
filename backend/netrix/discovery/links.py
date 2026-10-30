"""Maintain current links from completed protocol snapshots without losing history."""

from sqlalchemy import select

from .. import models as m
from ..core import now
from .neighbor_labels import neighbor_label


def legacy_match(link, neighbor):
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
    links = list(db.scalars(select(m.Link).where(m.Link.device_id == device.id).with_for_update()))
    seen = set()
    for neighbor in collected.get("neighbors", []):
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
            link = next((l for l in candidates if l.source == "cdp"), candidates[0] if candidates else None)
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
        candidates = list(
            db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id == device.vrf_id,
                    m.Device.id != device.id,
                    m.Device.archived.is_(False),
                    m.Device.name == neighbor["remote_name"],
                )
            )
        )
        link.confidence = 0.65 if len(candidates) == 1 else 0.5
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
