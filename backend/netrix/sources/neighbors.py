"""Separate LLDP/CDP facts; links contain references and operator preferences only."""

import hashlib

from .. import models as m
from .records import source_write


def read(link):
    result = {}
    for kind in ("lldp", "cdp"):
        row = getattr(link, kind)
        if row:
            raw = {
                c.name if c.name != "record_index" else "index": getattr(row, c.name)
                for c in row.__table__.columns
                if c.name not in {"id", "link_id", "created_at", "updated_at", "remote_name", "remote_port"}
                and getattr(row, c.name) not in (None, "")
            }
            if raw:
                result[kind] = raw
    if link.aggregate:
        result["local_aggregate"] = dict(
            name=link.aggregate, type=link.aggregate_type, source=link.aggregate_source
        )
    if link.stp_root is not None:
        result["spanning_tree"] = dict(port=link.stp_port, is_root=link.stp_root, source=link.stp_source)
    return result


@source_write
def write(db, link):
    from .network import port_for, state_for

    if "_pending_interface_name" in link.__dict__ or not link.local_port:
        device = db.get(m.Device, link.device_id)
        state = state_for(db, link.device_id, device.management_ip if device else "")
        link.local_port = port_for(state, link.interface_name)
    link.local_port.state.updated_at = m.now()
    data = link.__dict__.get("_pending_evidence", read(link))
    name = link.remote_name or ""
    port = link.remote_port or ""
    link.identity_key = hashlib.sha256((name + "\0" + port).encode()).hexdigest()
    if link.source == "manual":
        if link.manual_remote_name is None:
            link.manual_remote_name = name
            if link.manual_remote_device_id is None:
                link.manual_remote_device_id = link.remote_device_id
        if link.manual_remote_port is None:
            link.manual_remote_port = port
    else:
        kinds = [k for k in ("lldp", "cdp") if k in data] or [
            k for k in ("lldp", "cdp") if k in (link.source or "lldp")
        ]
        for kind in kinds:
            cls = m.LLDPNeighbor if kind == "lldp" else m.CDPNeighbor
            row = getattr(link, kind) or cls()
            raw = data.get(kind) or {}
            for col in cls.__table__.columns:
                key = "index" if col.name == "record_index" else col.name
                if key in raw:
                    value = raw[key]
                    if col.name == "local_port_number":
                        value = str(value)
                    setattr(row, col.name, value)
            # Canonical display fields are stored once, inside their protocol table.
            row.remote_name = name
            row.remote_port = port
            setattr(link, kind, row)
    if "local_aggregate" in data:
        agg = data.get("local_aggregate") or {}
        link.local_port.aggregate, link.local_port.aggregate_type, link.local_port.aggregate_source = (
            agg.get("name", ""),
            agg.get("type", ""),
            agg.get("source", ""),
        )
    stp = data.get("spanning_tree")
    if stp:
        link.local_port.state.stp_root, link.local_port.state.stp_port, link.local_port.state.stp_source = (
            stp.get("is_root"),
            stp.get("port"),
            stp.get("source", ""),
        )
    for key in (
        "_pending_evidence",
        "_pending_remote_name",
        "_pending_remote_port",
        "_pending_interface_name",
    ):
        link.__dict__.pop(key, None)
