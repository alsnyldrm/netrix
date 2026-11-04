"""Device locks must not lock the shared type catalog. Disposable MariaDB only."""

from uuid import uuid4

from netrix import models as m
from netrix.core import Base, engine, session_factory
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Dedicated disposable database required"
Base.metadata.create_all(engine())
sf = session_factory()
with sf() as db:
    vrf = m.VRF(name="Device lock " + uuid4().hex)
    kind = m.DeviceType(code=uuid4().hex[:20], name="Lock fixture " + uuid4().hex)
    db.add_all([vrf, kind])
    db.flush()
    devices = [
        m.Device(name=f"Lock fixture {i}", management_ip=f"192.0.2.{i}", vrf_id=vrf.id, kind=kind.code)
        for i in (1, 2)
    ]
    db.add_all(devices)
    db.commit()
    first_id, second_id = [device.id for device in devices]
    kind_id = kind.id

with sf() as first, sf() as second, sf() as catalog, sf() as same_device:
    first.scalar(select(m.Device).where(m.Device.id == first_id).with_for_update())
    second.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
    # Different devices sharing a type must remain independently writable.
    other = second.scalar(select(m.Device).where(m.Device.id == second_id).with_for_update())
    assert other.id == second_id
    # The type catalog must stay unlocked by either device read.
    catalog.scalar(select(m.DeviceType).where(m.DeviceType.id == kind_id).with_for_update(nowait=True))
    catalog.rollback()
    try:
        same_device.scalar(select(m.Device).where(m.Device.id == first_id).with_for_update(nowait=True))
    except OperationalError as exc:
        assert exc.orig.args[0] in (1205, 3572)
        same_device.rollback()
    else:
        raise AssertionError("The selected device must retain its exclusive lock")
    second.rollback()
    first.rollback()

with sf() as db:
    rows = list(db.scalars(select(m.Device).where(m.Device.id.in_([first_id, second_id]))))
# Eager type labels remain available after closing the session.
assert all(device.device_type.id == kind_id for device in rows)
print(
    "MariaDB device lock PASS: independent devices, unlocked type catalog, same-device exclusion, detached labels"
)
