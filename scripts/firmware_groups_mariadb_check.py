"""Disposable MariaDB only: legacy conflicts, unique membership and concurrent writers."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import HTTPException
from netrix import models as m
from netrix.core import engine, session_factory
from netrix.firmware.grouping import save_group
from netrix.firmware.service import GroupInput
from netrix.inventory.device_types import seed_defaults
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test", "Disposable test database required"


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    if blocked:
        assert result.returncode and "Resolve duplicate firmware" in result.stderr, result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", "20261103_36")
with session_factory()() as db:
    seed_defaults(db)
    vrf = m.VRF(name="Fixture")
    profile = m.Credential(name="Fixture", protocol="ssh", encrypted_secret="fixture-unused")
    db.add_all([vrf, profile])
    db.flush()
    scope = m.Scope(name="Fixture", cidr="192.0.2.0/24", credential_id=profile.id, vrf_id=vrf.id, vlan_vid=10)
    db.add(scope)
    db.flush()
    devices = [
        m.Device(
            name=f"Fixture {i}",
            management_ip=f"192.0.2.{i + 1}",
            vrf_id=vrf.id,
            discovery_scope_id=scope.id,
            adapter="aruba_6100",
            model="JL675A",
        )
        for i in range(2)
    ]
    groups = [m.FirmwareGroup(name=name) for name in ("Fixture A", "Fixture B")]
    db.add_all(devices + groups)
    db.flush()
    db.add_all(m.FirmwareMember(group_id=g.id, device_id=devices[0].id) for g in groups)
    db.commit()
    ids, group_ids = [d.id for d in devices], [g.id for g in groups]
migrate("upgrade", "20261103_39", blocked=True)
with session_factory()() as db:
    assert len(list(db.scalars(select(m.FirmwareMember)))) == 2, "Migration must not choose an owner"
    db.delete(db.get(m.FirmwareMember, (group_ids[1], ids[0])))
    db.commit()
migrate("upgrade", "20261103_39")
with engine().connect() as connection:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: (
                kind != "table" or name == "firmware_group_members"
            )
        },
    )
    assert not compare_metadata(context, m.Base.metadata)
with session_factory()() as db:
    db.add(m.FirmwareMember(group_id=group_ids[1], device_id=ids[0]))
    try:
        db.commit()
        raise AssertionError("Direct duplicate membership was accepted")
    except IntegrityError:
        db.rollback()

barrier = Barrier(2)


def compete(name):
    with session_factory()() as db:
        barrier.wait(timeout=10)
        try:
            save_group(db, None, GroupInput(name=name, device_ids=[ids[1]]), m.FirmwareGroup())
            return "saved"
        except HTTPException as exc:
            assert exc.status_code == 409
            return "conflict"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete, ("Race A", "Race B"))) == ["conflict", "saved"]
with session_factory()() as db:
    memberships = list(db.scalars(select(m.FirmwareMember).where(m.FirmwareMember.device_id == ids[1])))
    assert len(memberships) == 1
    owner = db.get(m.FirmwareGroup, memberships[0].group_id)
    owner_name = owner.name
    save_group(db, None, GroupInput(name=owner.name, description="Own edit", device_ids=[ids[1]]), owner)
    try:
        save_group(db, None, GroupInput(name="Must roll back", device_ids=[ids[0], ids[1]]), owner)
        raise AssertionError("Conflicting group update was accepted")
    except HTTPException as exc:
        assert exc.status_code == 409
    assert db.get(m.FirmwareGroup, owner.id).name == owner_name
    assert len(list(db.scalars(select(m.FirmwareMember).where(m.FirmwareMember.group_id == owner.id)))) == 1
migrate("downgrade", "20261103_36")
migrate("upgrade", "20261103_39")
print(
    "PASS: MariaDB legacy conflict guard, UNIQUE/schema parity, atomic rollback, own-group edits, concurrent membership race and migration roundtrip"
)
