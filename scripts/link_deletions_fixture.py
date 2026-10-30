"""Disposable browser-only rescan harness. Never queries real devices."""

import topology_fixture  # noqa: F401
from netrix import models as m
from netrix.core import session_factory
from netrix.discovery.links import sync_links
from sqlalchemy import select
from topology_fixture import app as app

snapshots = {}
with session_factory()() as db:
    for row in db.scalars(select(m.Link).where(m.Link.source != "manual")):
        snapshots.setdefault(row.device_id, []).append(
            {
                "interface_name": row.interface_name,
                "remote_name": row.remote_name,
                "remote_port": row.remote_port,
                "source": row.source,
                "evidence": row.evidence,
            }
        )


@app.post("/__fixture__/rescan")
def rescan():
    with session_factory()() as db:
        for device_id, neighbors in snapshots.items():
            sync_links(
                db,
                db.get(m.Device, device_id),
                {"neighbors": neighbors, "neighbor_protocols_complete": ["lldp", "cdp"]},
            )
        db.commit()
    return {"status": "done"}
