"""Deletion exclusions and stale workers on disposable MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.discovery.link_deletions import delete_link
from netrix.discovery.links import sync_links
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Only disposable netrix_test is allowed"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "20261030_11")
with session_factory()() as db:
    vrf = m.VRF(name="Deleted neighbors")
    db.add(vrf)
    db.flush()
    device = m.Device(name="Core", management_ip="192.0.2.1", vrf_id=vrf.id)
    db.add(device)
    db.flush()
    db.execute(
        text("""INSERT INTO topology_links
      (id, device_id, interface_name, remote_name, remote_port, source, confidence, evidence, is_current, created_at, updated_at)
      VALUES ('deleted-neighbor', :device, 'A2', 'Observed', 'NIC', 'lldp', 0.5, '{}', 1, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))"""),
        {"device": device.id},
    )
    db.commit()
    device_id = device.id
migrate("upgrade", "head")
migrate("check")
with session_factory()() as worker:
    stale = worker.get(m.Link, "deleted-neighbor")
    assert not stale.auto_add_excluded and stale.is_current
    with session_factory()() as writer:
        import netrix.services as svc

        svc.publish = lambda: None
        delete_link(writer, "deleted-neighbor", None)
    for attempt in range(2):
        try:
            sync_links(
                worker,
                worker.get(m.Device, device_id),
                {
                    "neighbors": [
                        {
                            "interface_name": "A2",
                            "remote_name": "Observed",
                            "remote_port": "NIC",
                            "source": "cdp",
                        }
                    ],
                    "neighbor_protocols_complete": ["lldp", "cdp"],
                },
            )
            worker.commit()
            break
        except OperationalError as exc:
            if attempt or exc.orig.args[0] != 1020:
                raise
            worker.rollback()
    worker.refresh(stale)
    assert stale.auto_add_excluded and not stale.is_current
    assert worker.scalar(text("SELECT COUNT(*) FROM topology_links")) == 1
    from netrix.inventory.management import query

    assert query(worker, "links")["total"] == 0
    assert query(worker, "topology-devices")["items"][0]["neighbor_count"] == 0
assert migrate("downgrade", "20261030_11", check=False).returncode != 0
with session_factory()() as db:
    # Only this disposable fixture is reset for the schema round trip.
    db.get(m.Link, "deleted-neighbor").auto_add_excluded = False
    db.commit()
migrate("downgrade", "20261030_11")
migrate("upgrade", "head")
migrate("check")
print(
    "MariaDB deletion PASS: legacy row, exclusion, stale worker, queries, downgrade guard, round trip, schema"
)
