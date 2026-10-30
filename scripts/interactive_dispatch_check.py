"""Real MariaDB/Redis admission and lane isolation on disposable infrastructure only."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from netrix import models as m
from netrix.core import engine, now, redis_client, session_factory
from netrix.discovery.interactive_tests import interactive_condition, start
from netrix.identity.security import encrypt
from netrix.worker import claim
from sqlalchemy import select

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    vrf = m.VRF(name="Interactive fixture")
    profile = m.Credential(
        name="Fixture",
        protocol="snmpv2c",
        encrypted_secret=encrypt(json.dumps({"community": "fixture-only"})),
    )
    db.add_all([vrf, profile])
    db.flush()
    db.add(m.Scope(name="Fixture", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=profile.id))
    devices = [
        m.Device(
            name=f"Fixture {i}",
            management_ip=f"192.0.2.{i + 1}",
            vrf_id=vrf.id,
            snmp_credential_id=profile.id,
        )
        for i in range(6)
    ]
    db.add_all(devices)
    db.flush()
    ids = [d.id for d in devices]
    background = m.Job(kind="backup", target_id=ids[0])
    db.add(background)
    db.commit()
    background_id = background.id
redis_client().set("netrix:tests:heartbeat", now().isoformat())
barrier = Barrier(6)


def submit(id):
    with session_factory()() as db:
        db.get(m.Device, id)  # Establish a pre-admission read view.
        barrier.wait(timeout=5)
        try:
            return start(db, "test_snmpv2c", id, None)["id"]
        except HTTPException as exc:
            assert exc.status_code in (429, 503), exc.detail
            return None


with ThreadPoolExecutor(max_workers=6) as pool:
    outcomes = list(pool.map(submit, ids))
accepted = [id for id in outcomes if id]
assert 1 <= len(accepted) <= 4
with session_factory()() as db:
    jobs = list(db.scalars(select(m.Job).where(interactive_condition())))
    assert {j.id for j in jobs} == set(accepted)
    assert len(list(db.scalars(select(m.Job).where(m.Job.kind == "test_snmpv2c")))) == len(accepted)
assert claim(interactive=False) == background_id
assert claim(interactive=False) is None
claimed = [claim(interactive=True) for _ in accepted]
assert set(claimed) == set(accepted) and claim(interactive=True) is None
print(
    f"MariaDB/Redis dispatch PASS: {len(accepted)} admitted, {6 - len(accepted)} rejected without queue, isolated lanes, concurrent stale read views"
)
