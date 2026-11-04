"""Exercise the avatar migration and constraints on disposable MariaDB only."""

import subprocess

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models  # noqa: F401
from netrix.core import Base, engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(action, revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", action, revision], check=True)


migrate("upgrade", "20261104_46")
with engine().begin() as db:
    db.execute(
        text(
            "INSERT INTO users (id,email,display_name,password_hash,role,ssh_access,is_active,created_at,updated_at) VALUES ('fixture','avatar@example.test','Avatar','fixture-hash','viewer',0,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
migrate("upgrade", "head")
with engine().begin() as db:
    assert db.scalar(text("SELECT display_name FROM users WHERE id='fixture'")) == "Avatar"
    db.execute(
        text(
            "INSERT INTO user_avatars (user_id,preset_id,image,version,updated_at) VALUES ('fixture',NULL,:image,'version',UTC_TIMESTAMP())"
        ),
        {"image": b"a" * 65535},
    )
    assert db.scalar(text("SELECT OCTET_LENGTH(image) FROM user_avatars")) == 65535
for statement in [
    "UPDATE user_avatars SET preset_id='naruto'",
    "UPDATE user_avatars SET image=NULL",
    "INSERT INTO user_avatars (user_id,preset_id,version,updated_at) VALUES ('absent','naruto','v',UTC_TIMESTAMP())",
    "INSERT INTO user_avatars (user_id,preset_id,version,updated_at) VALUES ('fixture','naruto','v',UTC_TIMESTAMP())",
]:
    try:
        with engine().begin() as db:
            db.execute(text(statement))
    except (IntegrityError, OperationalError):
        pass
    else:
        raise AssertionError("Avatar constraint not enforced")
with engine().begin() as db:
    db.execute(text("DELETE FROM users WHERE id='fixture'"))
    assert db.scalar(text("SELECT COUNT(*) FROM user_avatars")) == 0
with engine().connect() as connection:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, other: (
                kind != "table" or name == "user_avatars"
            )
        },
    )
    assert compare_metadata(context, Base.metadata) == []
migrate("downgrade", "20261104_46")
migrate("upgrade", "head")
print(
    "PASS: avatar schema parity, BLOB round trip, source/FK/unique constraints, cascade and migration round trip"
)
