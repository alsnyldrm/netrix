"""Run only against a disposable database called netrix_test, after Alembic upgrade."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.services import lock_vrf
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test", "Dedicated test database required"
with engine().connect() as connection:
    version = connection.scalar(text("SELECT VERSION()"))
    assert "MariaDB" in version
    assert connection.scalar(text("SELECT @@session.wsrep_sync_wait")) == 1
    assert connection.scalar(text("SELECT @@session.time_zone")) == "+00:00"
    assert len(inspect(connection).get_table_names()) >= 20
sf = session_factory()
with sf() as db:
    assert db.get(m.SystemState, "setup").value == "pending"
    vrf = m.VRF(name="integration")
    other = m.VRF(name="other")
    db.add_all([vrf, other])
    db.commit()
    vrf_id, other_id = vrf.id, other.id
    device = m.Device(name="test", management_ip="192.0.2.1", vrf_id=vrf_id)
    db.add(device)
    db.commit()
    assert db.get(m.Device, device.id).created_at.tzinfo is not None
    device.created_at = now().replace(microsecond=123456)
    db.commit()
    db.expire_all()
    assert db.get(m.Device, device.id).created_at.microsecond == 123456
    device_id = device.id
    prefix = m.Prefix(cidr="2001:db8::/64", vrf_id=vrf_id)
    db.add(prefix)
    db.commit()
    prefix_id = prefix.id
    db.add(m.IPAddress(address="2001:db8::1", vrf_id=vrf_id, prefix_id=prefix_id))
    db.commit()
    try:
        db.add(m.IPAddress(address="2001:db8::1", vrf_id=vrf_id, prefix_id=prefix_id))
        db.commit()
        raise AssertionError("Unique constraint missing")
    except (IntegrityError, OperationalError):
        db.rollback()
    try:
        db.add(m.VLAN(name="bad", domain="test", vid=5000))
        db.commit()
        raise AssertionError("Check constraint missing")
    except (IntegrityError, OperationalError):
        db.rollback()
    try:
        db.add(m.Device(name="bad", management_ip="192.0.2.2", vrf_id="missing"))
        db.commit()
        raise AssertionError("Foreign key constraint missing")
    except (IntegrityError, OperationalError):
        db.rollback()
    # DECIMAL(20,0) must retain unsigned 64-bit counters exactly.
    port = m.Interface(name="Gi1", device_id=device_id, if_index=1)
    db.add(port)
    job = m.Job(kind="monitor", target_id=device_id)
    db.add(job)
    db.flush()
    db.add(
        m.Sample(
            interface_id=port.id,
            job_id=job.id,
            in_octets=18446744073709551615,
            out_octets=18446744073709551614,
            uptime_ticks=1,
        )
    )
    db.commit()
    db.expire_all()
    sample = db.scalar(select(m.Sample))
    assert int(sample.in_octets) == 18446744073709551615
barrier = Barrier(2)


def competing_assignment(index):
    with sf() as db:
        barrier.wait()
        lock_vrf(db, vrf_id)
        if db.scalar(
            select(m.IPAddress).where(m.IPAddress.address == "2001:db8::2", m.IPAddress.vrf_id == vrf_id)
        ):
            return "existing"
        db.add(m.IPAddress(address="2001:db8::2", vrf_id=vrf_id, prefix_id=prefix_id))
        db.commit()
        return "created"


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(competing_assignment, [1, 2]))
assert sorted(results) == ["created", "existing"], results
with sf() as db:
    for index in range(2):
        db.add(m.Job(kind="monitor", target_id=device_id))
    db.commit()
with sf() as first, sf() as second:
    a = first.scalar(select(m.Job).where(m.Job.status == "queued").with_for_update(skip_locked=True).limit(1))
    b = second.scalar(
        select(m.Job).where(m.Job.status == "queued").with_for_update(skip_locked=True).limit(1)
    )
    assert a and b and a.id != b.id
print(
    "MariaDB integration PASS:",
    version,
    "migration, UTC, FK, CHECK, UNIQUE, uint64, concurrent VRF locking, SKIP LOCKED",
)
