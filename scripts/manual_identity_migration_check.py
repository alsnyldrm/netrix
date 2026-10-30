"""Manual inventory preferences on disposable MariaDB, including a stale worker."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.inventory.identity import apply_identity
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Only disposable netrix_test is allowed"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
with session_factory()() as db:
    vrf = m.VRF(name="Manual preference test")
    db.add(vrf)
    db.flush()
    device = m.Device(
        name="Edge",
        management_ip="192.0.2.1",
        vrf_id=vrf.id,
        vendor="Original vendor",
        model="Original model",
    )
    db.add(device)
    db.commit()
    device_id = device.id
migrate("downgrade", "20261030_09")
migrate("upgrade", "head")
migrate("check")
with session_factory()() as worker_db:
    device = worker_db.get(m.Device, device_id)
    assert device.manual_identity_fields == [] and device.model == "Original model"
    with session_factory()() as user_db:
        row = user_db.get(m.Device, device_id)
        row.vendor = "Managed vendor"
        row.manual_identity_fields = ["vendor"]
        user_db.commit()
    # MariaDB may reject the old read view with 1020. The worker retries the
    # transaction on OperationalError; either path must preserve the manual edit.
    for attempt in range(2):
        try:
            apply_identity(
                worker_db,
                device,
                {"vendor": "Observed vendor", "model": "Observed model", "kind": "switch"},
                None,
                "snmpv3",
            )
            break
        except OperationalError as exc:
            if attempt or exc.orig.args[0] != 1020:
                raise
            worker_db.rollback()
    worker_db.commit()
    assert device.vendor == "Managed vendor" and device.model == "Observed model"
assert migrate("downgrade", "20261030_09", check=False).returncode != 0
with session_factory()() as db:
    row = db.get(m.Device, device_id)
    assert row.manual_identity_fields == ["vendor"] and row.vendor == "Managed vendor"
    # Only the disposable fixture preferences are cleared for rollback verification.
    db.execute(text("UPDATE devices SET manual_identity_fields = '[]'"))
    db.commit()
migrate("downgrade", "20261030_09")
migrate("upgrade", "head")
migrate("check")
print(
    "MariaDB manual preferences PASS: legacy data, JSON default, stale worker, guarded downgrade, round trip, schema"
)
