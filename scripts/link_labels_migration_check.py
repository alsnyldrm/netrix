"""User labels and rollback guards on disposable MariaDB; never production data."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.discovery.link_edits import update_labels
from netrix.schemas import LinkLabelsInput
from netrix.services import serialize
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Only disposable netrix_test is allowed"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


# The old schema's existing observation must remain intact.
migrate("upgrade", "20261030_10")
with session_factory()() as db:
    vrf = m.VRF(name="Link labels")
    db.add(vrf)
    db.flush()
    device = m.Device(name="Core", management_ip="192.0.2.1", vrf_id=vrf.id)
    db.add(device)
    db.flush()
    db.execute(
        text("""INSERT INTO topology_links
      (id, device_id, interface_name, remote_name, remote_port, source, confidence, evidence, is_current, created_at, updated_at)
      VALUES ('label-fixture', :device, 'A2', 'Observed', 'NIC', 'lldp', 0.5, '{}', 1, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))"""),
        {"device": device.id},
    )
    db.commit()
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    link = db.get(m.Link, "label-fixture")
    assert link.manual_remote_name is None and serialize(link)["remote_name"] == "Observed"
    # The old worker's row can update its own observed fields without replacing a user edit.
    with session_factory()() as writer:
        import netrix.services as svc

        svc.publish = lambda: None
        update_labels(writer, link.id, LinkLabelsInput(remote_name="Manual", remote_port="49"), None)
    for attempt in range(2):
        try:
            link.remote_port = "New observed port"
            db.commit()
            break
        except OperationalError as exc:
            # MariaDB rejects stale read views; the worker retries this transaction.
            if attempt or exc.orig.args[0] != 1020:
                raise
            db.rollback()
    db.refresh(link)
    assert link.manual_remote_name == "Manual" and serialize(link)["remote_port"] == "49"
    from netrix.inventory.management import query

    result = query(db, "links", filters='[{"field":"remote_name","op":"eq","value":"Manual"}]')
    assert result["total"] == 1 and result["items"][0]["confidence_percent"] == 50
assert migrate("downgrade", "20261030_10", check=False).returncode != 0
with session_factory()() as db:
    update_labels(db, "label-fixture", LinkLabelsInput(remote_name=None, remote_port=None), None)
migrate("downgrade", "20261030_10")
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    link = db.get(m.Link, "label-fixture")
    assert link.remote_name == "Observed" and link.remote_port == "New observed port"
print(
    "MariaDB link labels PASS: legacy row, override, stale writer, query, guarded downgrade, round trip, schema"
)
