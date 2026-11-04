"""Reproduce the VRF mutex snapshot conflict (MariaDB 1020) against disposable netrix_test only."""

import time
from concurrent.futures import ThreadPoolExecutor

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.services import lock_vrf, save_resource
from sqlalchemy import select, text
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Disposable database required"
with engine().connect() as connection:
    assert connection.scalar(text("SELECT @@innodb_snapshot_isolation")) == 1
    assert connection.scalar(text("SELECT @@transaction_isolation")) == "REPEATABLE-READ"
sf = session_factory()
with sf() as db:
    vrf = m.VRF(name="Snapshot fixture")
    user = m.User(email="snapshot@example.test", display_name="Test", password_hash="unused", role="admin")
    db.add_all([vrf, user])
    db.flush()
    vlan = m.VLAN(vid=60, name="VLAN-60", cidr="192.0.2.0/24", vrf_id=vrf.id)
    db.add(vlan)
    db.flush()
    address = m.IPAddress(address="192.0.2.10", vrf_id=vrf.id, vlan_id=vlan.id, status="active")
    db.add(address)
    db.commit()
    vrf_id, user_id, vlan_id, address_id = vrf.id, user.id, vlan.id, address.id


def bump():
    # An IPAM worker persisting one observation.
    with sf() as worker:
        lock_vrf(worker, vrf_id)
        worker.commit()


# The environment reproduces production: a stale snapshot rejects the raw mutex write.
with sf() as api:
    api.get(m.User, user_id)
    bump()
    try:
        api.execute(
            insert(m.SystemState).values(key="vrf:" + vrf_id, value="1").on_duplicate_key_update(value="0")
        )
    except OperationalError as exc:
        assert exc.orig.args[0] == 1020, exc.orig.args
    else:
        raise AssertionError("MariaDB did not reject the stale mutex write")
    api.rollback()
print("PASS: stale snapshot reproduces MariaDB 1020 on the raw mutex write")


def payload(**changes):
    return {"address": "192.0.2.10", "vrf_id": vrf_id, "vlan_id": vlan_id, "status": "active", **changes}


# Production pattern: authentication read, worker commit, then the address edit.
with sf() as api:
    actor = api.get(m.User, user_id)
    bump()
    saved = save_resource(api, "addresses", payload(hostname="edited"), actor, address_id)
    assert saved["hostname"] == "edited"
print("PASS: address edit after a concurrent worker commit saved without 1020")


# A worker holding the mutex across a batch: the API waits, then must still succeed.
with sf() as worker:
    lock_vrf(worker, vrf_id)

    def edit():
        with sf() as api:
            actor = api.get(m.User, user_id)
            started = time.monotonic()
            saved = save_resource(api, "addresses", payload(hostname="after-wait"), actor, address_id)
            return saved["hostname"], time.monotonic() - started

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(edit)
        time.sleep(1)
        assert not pending.done(), "API edit did not wait for the worker mutex"
        worker.commit()
        hostname, waited = pending.result(timeout=15)
    assert hostname == "after-wait"
print(f"PASS: address edit waited {waited:.2f}s for the worker batch and then saved")

# Rewinding must never discard caller writes.
with sf() as api:
    api.add(m.Event(kind="fixture", message="caller work"))
    api.flush()
    api.scalar(select(m.SystemState.value).where(m.SystemState.key == "vrf:" + vrf_id))
    bump()
    try:
        lock_vrf(api, vrf_id)
    except OperationalError as exc:
        assert exc.orig.args[0] == 1020, exc.orig.args
    else:
        raise AssertionError("Transaction with writes rewound or bypassed snapshot isolation")
    api.rollback()
print("PASS: transaction with pending writes still surfaces the conflict instead of rewinding")
