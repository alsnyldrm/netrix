"""Dependency deletion checks against an isolated netrix_test MariaDB only."""

from types import SimpleNamespace

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.inventory.device_types import seed_defaults
from netrix.ipam.prefix_deletion import preview, remove
from netrix.ipam.service import observe
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test"
with session_factory()() as db:
    seed_defaults(db)
    vrf = m.VRF(name="prefix-delete-test")
    db.add(vrf)
    db.flush()
    p = m.Prefix(cidr="192.0.2.0/24", vrf_id=vrf.id)
    q = m.Prefix(cidr="198.51.100.0/24", vrf_id=vrf.id)
    db.add_all([p, q])
    db.flush()
    ip = m.IPAddress(prefix_id=p.id, vrf_id=vrf.id, address="192.0.2.1")
    device = m.Device(name="preserved", management_ip=ip.address, vrf_id=vrf.id)
    config = m.Integration(
        name="fixture",
        kind="vcenter",
        host="fixture.invalid",
        port=443,
        prefix_ids=[p.id, q.id],
        encrypted_secret="unused",
    )
    db.add_all([ip, device, config])
    db.flush()
    db.add(m.IPObservation(address_id=ip.id, source="icmp", source_key=p.id, data={}))
    db.add(m.IPTraffic(address_id=ip.id, source_key="fixture", sampled_at=now(), interval_seconds=5))
    queued = m.Job(kind="ipam_ping", target_id=p.id, active_key="ipam_ping:" + p.id, status="queued")
    running = m.Job(
        kind="integration", target_id=config.id, active_key="integration:" + config.id, status="running"
    )
    db.add_all([queued, running])
    db.commit()
    job_ids = queued.id, running.id
    stale = session_factory()()
    old_prefix = stale.get(m.Prefix, p.id)  # Snapshot before deletion.
    stale.expunge(old_prefix)
    ids = (p.id, q.id, device.id, config.id)
    token = preview(db, [p.id])["confirmation"]
    result = remove(db, [p.id], SimpleNamespace(id=None, role="admin"), token)
    assert result == {"affected": 1, "deleted_addresses": 1}
with session_factory()() as db:
    assert db.get(m.Prefix, ids[0]) is None and db.get(m.Prefix, ids[1])
    assert db.get(m.Device, ids[2])
    assert db.get(m.Integration, ids[3]).prefix_ids == [ids[1]]
    assert db.get(m.Job, job_ids[0]).status == "cancelled"
    assert db.get(m.Job, job_ids[0]).active_key is None
    assert db.get(m.Job, job_ids[1]).cancel_requested
    assert db.get(m.Job, job_ids[1]).active_key  # Held until the worker acknowledges.
    assert not list(db.scalars(select(m.IPAddress)))
    assert not list(db.scalars(select(m.IPObservation)))
    assert not list(db.scalars(select(m.IPTraffic)))

try:
    assert observe(stale, old_prefix, "192.0.2.9", "inventory", "fixture", {}) is None
except OperationalError as exc:
    # MariaDB snapshot isolation may reject the stale locking read itself.
    # The worker retries/acknowledges cancellation; no deleted IP may reappear.
    assert exc.orig.args[0] == 1020
    stale.rollback()
    assert observe(stale, old_prefix, "192.0.2.9", "inventory", "fixture", {}) is None
stale.commit()
stale.close()
print(
    "MariaDB: prefix/IP/observation/traffic deletion, job cancellation, stale collector and inventory/integration preservation PASS"
)
