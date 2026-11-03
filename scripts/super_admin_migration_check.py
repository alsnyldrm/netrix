"""MariaDB constraints and migration preservation on disposable netrix_test only."""

import subprocess

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import Base, engine, session_factory
from netrix.identity.permissions import SUPER_ADMIN_EMAIL, can_ssh, is_admin
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test", "Disposable database required"


def migrate(*args):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=True)


migrate("upgrade", "20261103_42")
with session_factory()() as db:
    owner = m.User(
        email=SUPER_ADMIN_EMAIL, display_name="Owner", role="admin", password_hash="unchanged-owner-hash"
    )
    admin = m.User(
        email="admin@example.test", display_name="Admin", role="admin", password_hash="unchanged-admin-hash"
    )
    granted = m.User(
        email="granted@example.test",
        display_name="Granted",
        role="operator",
        ssh_access=True,
        password_hash="unchanged-granted-hash",
    )
    db.add_all([owner, admin, granted])
    db.commit()
    owner_id, admin_id, granted_id = owner.id, admin.id, granted.id
    before_tables = set(inspect(engine()).get_table_names())
migrate("upgrade", "head")
with session_factory()() as db:
    owner, admin, granted = [db.get(m.User, id) for id in (owner_id, admin_id, granted_id)]
    assert owner.role == "super_admin" and is_admin(owner) and can_ssh(owner)
    assert admin.role == "admin" and not admin.ssh_access and not can_ssh(admin)
    assert granted.role == "operator" and granted.ssh_access and can_ssh(granted)
    assert [owner.password_hash, admin.password_hash, granted.password_hash] == [
        "unchanged-owner-hash",
        "unchanged-admin-hash",
        "unchanged-granted-hash",
    ]
    assert set(inspect(engine()).get_table_names()) == before_tables
    for sql in (
        "UPDATE users SET role = 'super_admin' WHERE email = 'admin@example.test'",
        "UPDATE users SET email = 'stolen@example.test' WHERE role = 'super_admin'",
        "UPDATE users SET role = 'invented' WHERE email = 'admin@example.test'",
    ):
        try:
            db.execute(text(sql))
            db.commit()
        except DBAPIError as exc:
            assert exc.orig.args[0] == 4025, "Expected MariaDB CHECK failure"
            db.rollback()
        else:
            raise AssertionError("MariaDB accepted a forbidden role mutation")
    assert len(list(db.scalars(select(m.User).where(m.User.role == "super_admin")))) == 1
migrate("downgrade", "20261103_42")
with session_factory()() as db:
    assert db.get(m.User, owner_id).role == "admin"
    assert db.get(m.User, owner_id).ssh_access
    assert not db.get(m.User, admin_id).ssh_access
migrate("upgrade", "head")
with engine().connect() as connection:
    # MariaDB reflection loses DESC on unrelated audit indexes. Compare users only.
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                type_ != "table" or name == "users"
            ),
        },
    )
    assert compare_metadata(context, Base.metadata) == []
print(
    "MariaDB super-admin migration PASS: unique owner, real CHECK enforcement, explicit SSH grants preserved, password hashes unchanged, no new tables, downgrade/upgrade, users metadata match"
)
