"""Reproduce scope-save contention against disposable MariaDB netrix_test only."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.identity.security import encrypt
from netrix.services import lock_vrf, save_resource
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test", "Disposable database required"
sf = session_factory()
with sf() as db:
    vrf = m.VRF(name="Contention fixture")
    institution = m.Institution(name="Fixture institution", code="TEST")
    user = m.User(email="contention@example.test", display_name="Test", password_hash="unused", role="admin")
    credential = m.Credential(
        name="Fixture SNMP", protocol="snmpv2c", encrypted_secret=encrypt('{"community":"fixture"}')
    )
    db.add_all([vrf, institution, user, credential])
    db.flush()
    site = m.Site(name="Campus", code="CAMPUS", institution_id=institution.id)
    prefix = m.Prefix(cidr="192.0.2.0/24", vrf_id=vrf.id)
    db.add_all([site, prefix])
    db.commit()
    vrf_id, user_id, prefix_id = vrf.id, user.id, prefix.id
    payload = dict(
        name="VLAN-60",
        cidr="10.6.0.0/21",
        vrf_id=vrf.id,
        institution_id=institution.id,
        site_id=site.id,
        credential_ids=[credential.id],
    )

# Hold precisely the same serialization lock as a worker persisting a batch.
with sf() as worker:
    lock_vrf(worker, vrf_id)

    def save_scope():
        with sf() as api:
            api.execute(text("SET SESSION innodb_lock_wait_timeout=1"))
            started = time.monotonic()
            try:
                saved = save_resource(api, "scopes", payload, api.get(m.User, user_id), commit=False)
                # Saving and editing both flush FK checks while the worker retains its lock.
                updated = save_resource(
                    api,
                    "scopes",
                    {**payload, "name": "VLAN-60 edited"},
                    api.get(m.User, user_id),
                    saved["id"],
                    commit=False,
                )
                assert updated["name"] == "VLAN-60 edited"
                elapsed = time.monotonic() - started
                assert elapsed < 1, elapsed
                api.commit()
                return elapsed
            except OperationalError as exc:
                raise AssertionError(
                    f"Scope save blocked by worker: DB code {exc.orig.args[0]} after {time.monotonic() - started:.2f}s"
                ) from None

    with ThreadPoolExecutor(max_workers=1) as pool:
        elapsed = pool.submit(save_scope).result(timeout=10)
    worker.rollback()
print(f"PASS: scope create/edit completed in {elapsed:.3f}s while worker retained its VRF write lock")

# IP writers must still serialize; the fix may not remove duplicate protection.
barrier = Barrier(2)


def allocate(_):
    with sf() as db:
        barrier.wait()
        lock_vrf(db, vrf_id)
        if db.scalar(
            select(m.IPAddress).where(m.IPAddress.vrf_id == vrf_id, m.IPAddress.address == "192.0.2.1")
        ):
            return "existing"
        db.add(m.IPAddress(vrf_id=vrf_id, prefix_id=prefix_id, address="192.0.2.1"))
        db.commit()
        return "created"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(allocate, [1, 2])) == ["created", "existing"]
print("PASS: concurrent IP allocation retains one record")
