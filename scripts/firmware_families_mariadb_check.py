"""Family migration on disposable MariaDB: hashes, IDs, model limits and history survive."""

import json
import subprocess
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test"


def migrate(direction, revision, blocked=False):
    result = subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", direction, revision], capture_output=True, text=True
    )
    if blocked:
        assert result.returncode and "refuse arbitrary family assignment" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", "20261104_47")
rows = [
    (str(uuid4()), version, models, family)
    for version, models, family in [
        ("K.16.02.0036", ["J8697A"], "aos_s_54xx"),
        ("KB.16.11.0032", ["J9850A", "J9851A"], "aos_s_54xx"),
        ("WB.16.10.0020", ["J9726A"], "aos_s_29xx"),
        ("WC.16.11.0032", ["JL256A", "JL261A"], "aos_s_29xx"),
    ]
]
insert = text(
    "INSERT INTO firmware_images(id,created_at,updated_at,name,family,version,models,original_name,size_bytes,sha256,expected_sha256,notes,status) VALUES (:id,:now,:now,'Existing image','aos_s',:version,:models,'existing.swi',123,:hash,:hash,'Keep release notes','ready')"
)
with engine().begin() as conn:
    for id, version, models, family in rows:
        conn.execute(
            insert,
            {
                "id": id,
                "now": now().replace(tzinfo=None),
                "version": version,
                "models": json.dumps(models),
                "hash": "a" * 64,
            },
        )
    bad = str(uuid4())
    conn.execute(
        insert,
        {
            "id": bad,
            "now": now().replace(tzinfo=None),
            "version": "ZZ.16.11.0001",
            "models": "[]",
            "hash": "a" * 64,
        },
    )
migrate("upgrade", "head", blocked=True)
with engine().begin() as conn:
    assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261104_47"
    conn.execute(text("DELETE FROM firmware_images WHERE id=:id"), {"id": bad})
with session_factory()() as db:
    vrf = m.VRF(name="Family migration fixture")
    db.add(vrf)
    db.flush()
    device = m.Device(
        name="Existing switch", management_ip="192.0.2.1", vrf_id=vrf.id, model="J9850A", adapter="aruba_5400"
    )
    plan = m.FirmwarePlan(
        name="Existing completed plan",
        status="succeeded",
        mode="stage",
        steps=[],
        concurrency=10,
        available_at=now(),
    )
    db.add_all([device, plan])
    db.flush()
    target = m.FirmwareTarget(
        plan_id=plan.id,
        device_id=device.id,
        image_id=rows[1][0],
        stage=0,
        status="staged",
        bank="primary",
        evidence={"staged": True},
    )
    db.add(target)
    db.flush()
    event = m.FirmwareEvent(
        target_id=target.id,
        kind="command",
        phase="preflight",
        title="Existing result",
        command="show flash",
        response="KB.16.11.0032",
        status="succeeded",
    )
    db.add(event)
    db.commit()
    target_id, event_id = target.id, event.id


def verify():
    with session_factory()() as db:
        for id, version, models, family in rows:
            image = db.get(m.FirmwareImage, id)
            assert image.family == family and image.version == version and image.models == models
            assert image.sha256 == image.expected_sha256 == "a" * 64 and image.size_bytes == 123
            assert image.notes == "Keep release notes" and image.status == "ready"
        assert db.get(m.FirmwareTarget, target_id).image_id == rows[1][0]
        assert db.get(m.FirmwareEvent, event_id).response == "KB.16.11.0032"


migrate("upgrade", "head")
verify()
with engine().connect() as conn:
    differences = compare_metadata(
        MigrationContext.configure(
            conn,
            opts={
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "firmware_images"
                )
            },
        ),
        m.Base.metadata,
    )
    assert not differences, differences
for invalid in ("aos_s", "invented"):
    try:
        with engine().begin() as conn:
            conn.execute(
                text("UPDATE firmware_images SET family=:family WHERE id=:id"),
                {"family": invalid, "id": rows[0][0]},
            )
        raise AssertionError("MariaDB accepted removed or unknown family")
    except DBAPIError as exc:
        assert exc.orig.args[0] == 4025
migrate("downgrade", "20261104_47")
with engine().connect() as conn:
    assert conn.execute(text("SELECT COUNT(*) FROM firmware_images WHERE family='aos_s'")).scalar_one() == 4
migrate("upgrade", "head")
verify()
print(
    "PASS: legacy K/KB and WB/WC separation, unknown-branch refusal, MariaDB constraints/schema parity, image/hash/model/history retention and lossless downgrade/re-upgrade"
)
