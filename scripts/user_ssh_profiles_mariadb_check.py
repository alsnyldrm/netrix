"""Disposable MariaDB only: lossless legacy secret migration, scoped UNIQUE/FK and racing edits."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.access import service
from netrix.access.schemas import GroupInput, SSHProfile
from netrix.core import Base, engine, session_factory
from netrix.identity.security import encrypt
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"
assert engine().dialect.name in ("mysql", "mariadb")


def migrate(target, downgrade=False):
    return subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "downgrade" if downgrade else "upgrade", target],
        capture_output=True,
    )


r = migrate("20261103_36")
assert r.returncode == 0, r.stderr.decode()
legacy_secret = encrypt(
    '{"username":"legacy-user","password":"legacy-secret","port":22,"connect_timeout":10,"initial_command":"no page"}'
)
with engine().begin() as conn:
    conn.execute(
        text(
            "INSERT INTO users(id,email,display_name,password_hash,role,is_active,ssh_access,created_at,updated_at) VALUES ('owner-a','a@example.test','A','unused','admin',1,0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)),('owner-b','b@example.test','B','unused','admin',1,0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    conn.execute(
        text(
            "INSERT INTO access_groups(id,owner_id,name,description,created_at,updated_at) VALUES ('legacy-group','owner-a','Legacy','Preserved',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    conn.execute(
        text(
            "INSERT INTO user_workspaces(user_id,preferences,encrypted_ssh,encrypted_commands) VALUES ('owner-a',:preferences,:secret,:commands)"
        ),
        {"preferences": '{"palette":"amber"}', "secret": legacy_secret, "commands": encrypt("[]")},
    )
# Exercise backfill with real pre-migration memberships and reject ambiguous legacy data.
with session_factory()() as db:
    vrf = m.VRF(name="Legacy VRF")
    credential = m.Credential(name="Legacy SNMP", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add_all([vrf, credential])
    db.flush()
    scope = m.Scope(name="Legacy scope", cidr="198.51.100.0/24", vrf_id=vrf.id, credential_id=credential.id)
    db.add(scope)
    db.flush()
    device = m.Device(
        name="Legacy device", management_ip="198.51.100.1", vrf_id=vrf.id, discovery_scope_id=scope.id
    )
    db.add(device)
    db.commit()
    legacy_device_id = device.id
with engine().begin() as conn:
    conn.execute(
        text("INSERT INTO access_group_devices(group_id,device_id) VALUES ('legacy-group',:id)"),
        {"id": legacy_device_id},
    )
    conn.execute(
        text(
            "INSERT INTO access_groups(id,owner_id,name,description,created_at,updated_at) VALUES ('duplicate-legacy','owner-a','Duplicate legacy','',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    conn.execute(
        text("INSERT INTO access_group_devices(group_id,device_id) VALUES ('duplicate-legacy',:id)"),
        {"id": legacy_device_id},
    )
r = migrate("head")
assert r.returncode != 0 and b"Resolve duplicate device memberships" in r.stderr
with engine().begin() as conn:
    assert "user_ssh_profiles" not in inspect(conn).get_table_names()
    conn.execute(text("DELETE FROM access_groups WHERE id='duplicate-legacy'"))
r = migrate("head")
assert r.returncode == 0, r.stderr.decode()
with engine().connect() as conn:
    tables = {"users", "user_workspaces", "user_ssh_profiles", "access_groups", "access_group_devices"}
    ctx = MigrationContext.configure(
        conn,
        opts={
            "compare_type": True,
            "include_object": lambda obj, name, kind, reflected, compared: (
                name in tables if kind == "table" else True
            ),
        },
    )
    differences = compare_metadata(ctx, Base.metadata)
    assert not differences, differences
    assert "encrypted_ssh" not in {c["name"] for c in inspect(conn).get_columns("user_workspaces")}
with session_factory()() as db:
    owner = db.get(m.User, "owner-a")
    migrated = db.scalar(select(m.UserSSHProfile).where(m.UserSSHProfile.owner_id == owner.id))
    assert service.resolve_profile(db, owner, legacy_device_id)[1]["username"] == "legacy-user"
    assert db.get(m.AccessGroupDevice, ("legacy-group", legacy_device_id)).owner_id == owner.id
    assert migrated.encrypted_ssh == legacy_secret
    assert "legacy-secret" not in migrated.encrypted_ssh
    assert db.get(m.AccessGroup, "legacy-group").ssh_profile_id == migrated.id
    assert db.get(m.UserWorkspace, owner.id).preferences == {"palette": "amber"}
    assert service.preferences(db, owner)["design"] == "atlas"
    vrf = m.VRF(name="Fixture VRF")
    cred = m.Credential(name="Fixture", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add_all([vrf, cred])
    db.flush()
    scope = m.Scope(name="Fixture", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=cred.id)
    db.add(scope)
    db.flush()
    device = m.Device(name="Fixture", management_ip="192.0.2.1", vrf_id=vrf.id, discovery_scope_id=scope.id)
    db.add(device)
    db.commit()
    device_id = device.id
    group = service.save_group(db, owner, GroupInput(name="A devices", device_ids=[device_id]))
    other = service.save_group(
        db, db.get(m.User, "owner-b"), GroupInput(name="B devices", device_ids=[device_id])
    )
    # Another account can group its own view, but cannot bind to our credentials.
    try:
        db.execute(
            text("UPDATE access_groups SET ssh_profile_id=:id WHERE id=:group"),
            {"id": migrated.id, "group": other["id"]},
        )
        db.commit()
        raise AssertionError("Cross owner profile accepted")
    except IntegrityError:
        db.rollback()
    empty = service.save_group(db, owner, GroupInput(name="Empty"))
    try:
        db.add(m.AccessGroupDevice(group_id=empty["id"], owner_id=owner.id, device_id=device_id))
        db.commit()
        raise AssertionError("Duplicate device accepted")
    except IntegrityError:
        db.rollback()
    try:
        db.add(m.AccessGroupDevice(group_id=empty["id"], owner_id="owner-b", device_id=device_id))
        db.commit()
        raise AssertionError("Cross owner member accepted")
    except IntegrityError:
        db.rollback()
    result = service.save_ssh(
        db,
        owner,
        SSHProfile(name="New account", username="new-user", password="new-secret", group_ids=[group["id"]]),
    )
    assert service.resolve_profile(db, owner, device_id)[1]["username"] == "new-user"
    assert result["has_password"] and "password" not in result
    service.delete_profile(db, owner, result["id"])
    assert db.get(m.AccessGroup, group["id"]).ssh_profile_id is None
    assert db.get(m.UserSSHProfile, migrated.id).encrypted_ssh == legacy_secret
r = migrate("20261103_36", True)
assert r.returncode != 0 and b"Remove SSH profiles" in r.stderr
# Serialize same-owner API transactions; exactly one concurrent group gets the device.
with session_factory()() as db:
    service.save_group(
        db, db.get(m.User, "owner-a"), GroupInput(name="A devices", device_ids=[]), group["id"]
    )
barrier = Barrier(2)


def compete(name):
    from fastapi import HTTPException

    with session_factory()() as db:
        user = db.get(m.User, "owner-a")
        barrier.wait()
        try:
            service.save_group(db, user, GroupInput(name=name, device_ids=[device_id]))
            return "saved"
        except HTTPException as exc:
            db.rollback()
            assert exc.status_code == 409
            return "conflict"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete, ["Race A", "Race B"])) == ["conflict", "saved"]


def compete_profile(name):
    from fastapi import HTTPException

    with session_factory()() as db:
        user = db.get(m.User, "owner-a")
        barrier.wait()
        try:
            service.save_ssh(
                db,
                user,
                SSHProfile(name=name, username="race-user", password="race-secret", group_ids=[empty["id"]]),
            )
            return "saved"
        except HTTPException as exc:
            db.rollback()
            assert exc.status_code == 409
            return "conflict"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete_profile, ["Race profile A", "Race profile B"])) == ["conflict", "saved"]
with session_factory()() as db:
    for id in list(db.scalars(select(m.UserSSHProfile.id))):
        service.delete_profile(db, db.get(m.User, "owner-a"), id)
r = migrate("20261103_36", True)
assert r.returncode == 0, r.stderr.decode()
r = migrate("head")
assert r.returncode == 0, r.stderr.decode()
with session_factory()() as db:
    assert db.get(m.UserWorkspace, "owner-a").preferences == {"palette": "amber"}
    assert db.get(m.Device, device_id).name == "Fixture"
print(
    "MariaDB: revision 40, schema parity, ciphertext preservation, group routing, owner isolation, UNIQUE/FK, concurrent edits, guarded downgrade and round trip passed"
)
