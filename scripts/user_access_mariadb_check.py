"""Disposable MariaDB netrix_test only: migration parity, UTC and authorization constraints."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.access.schemas import GroupInput
from netrix.access.service import save_group
from netrix.core import Base, engine, session_factory
from netrix.identity.security import encrypt
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test", "Disposable MariaDB netrix_test required"
assert engine().dialect.name in ("mysql", "mariadb")
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "20261103_33"], check=True)
with engine().begin() as conn:
    conn.execute(
        text(
            "INSERT INTO users (id, email, display_name, password_hash, role, is_active, created_at, updated_at) VALUES ('old-user','old@example.test','Existing user','unused','admin',1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)


def schema_parity():
    # MariaDB reflects pre-existing revision 33 DESC journal indexes without sort
    # expressions. Restrict parity to revision 34's tables, rather than pretending
    # those unrelated baseline reflection differences belong to this migration.
    tables = {"user_workspaces", "access_groups", "access_group_devices", "access_group_users"}
    with engine().connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, kind, reflected, compared: (
                    name in tables if kind == "table" else True
                ),
            },
        )
        assert not compare_metadata(context, Base.metadata)


schema_parity()
with session_factory()() as db:
    user = db.get(m.User, "old-user")
    assert user.display_name == "Existing user" and user.created_at.tzinfo
    vrf = m.VRF(name="Access fixture")
    credential = m.Credential(name="Fixture SNMP", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add_all([vrf, credential])
    db.flush()
    scope = m.Scope(name="Fixture", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=credential.id)
    db.add(scope)
    db.flush()
    device = m.Device(name="Fixture", management_ip="192.0.2.1", vrf_id=vrf.id, discovery_scope_id=scope.id)
    db.add(device)
    db.flush()
    db.add(
        m.UserWorkspace(
            user_id=user.id, preferences={"palette": "teal"}, encrypted_ssh=encrypt('{"password":"fixture"}')
        )
    )
    db.commit()
    device_id = device.id
    payload = GroupInput(name="Fixture grant", device_ids=[device_id], user_ids=[user.id], ssh_enabled=True)
    group_id = save_group(db, user, payload)["id"]
    assert db.get(m.AccessGroup, group_id).created_at.tzinfo
    for sql in (
        "INSERT INTO access_group_users(group_id,user_id) VALUES ('missing','old-user')",
        "INSERT INTO access_group_users(group_id,user_id) VALUES (:id,'old-user')",
        "INSERT INTO access_group_devices(group_id,device_id) VALUES (:id,'missing')",
        "INSERT INTO user_workspaces(user_id,preferences) VALUES ('missing','{}')",
    ):
        try:
            db.execute(text(sql), {"id": group_id})
            db.commit()
            raise AssertionError("Constraint accepted invalid data")
        except IntegrityError:
            db.rollback()
    assert db.get(m.UserWorkspace, "old-user").preferences["palette"] == "teal"
    assert "fixture" not in db.get(m.UserWorkspace, "old-user").encrypted_ssh

barrier = Barrier(2)


def compete(_):
    with session_factory()() as db:
        user = db.get(m.User, "old-user")
        barrier.wait()
        try:
            save_group(db, user, GroupInput(name="Concurrent group"))
            return "saved"
        except IntegrityError:
            db.rollback()
            return "conflict"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete, range(2))) == ["conflict", "saved"]

result = subprocess.run(
    ["alembic", "-c", "backend/alembic.ini", "downgrade", "20261103_33"], capture_output=True
)
assert result.returncode != 0 and b"Remove saved workspaces" in result.stderr
with session_factory()() as db:
    db.execute(delete(m.AccessGroup))
    assert not list(db.scalars(select(m.AccessGroupUser)))
    assert not list(db.scalars(select(m.AccessGroupDevice)))
    db.execute(delete(m.UserWorkspace))
    db.commit()
subprocess.run(["alembic", "-c", "backend/alembic.ini", "downgrade", "20261103_33"], check=True)
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
schema_parity()
with session_factory()() as db:
    assert db.get(m.User, "old-user").display_name == "Existing user"
    assert db.get(m.Device, device_id).name == "Fixture"
print(
    "MariaDB: upgrade/check, preserved existing data, UTC, encrypted workspace, FK/UNIQUE, concurrent group creation, cascade, guarded downgrade and round-trip passed"
)
