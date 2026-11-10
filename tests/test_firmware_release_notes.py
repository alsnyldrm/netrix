"""Release notes persist separately from upgrade instructions and never change firmware."""

from netrix import models as m
from netrix.firmware.service import image_path
from sqlalchemy import event, func, select
from test_firmware import CONTENT, DIGEST
from test_firmware import fw as firmware_fixture

fw = firmware_fixture
NOTES = "Yeni özellikler\n• SSH düzeltmesi\n\nBilinen sorun: <script>alert('notes')</script>"


def test_upload_preserves_release_notes_and_lists_do_not_read_large_notes(fw):
    c = fw["client"]
    response = c.post(
        "/api/v1/firmware/images",
        json={
            "name": "Release notes upload",
            "family": "cx6100",
            "version": "PL.10.18.1010",
            "original_name": "release.swi",
            "expected_sha256": DIGEST,
            "notes": "BootROM ve kurtarma talimatları",
            "release_notes": NOTES,
        },
    )
    assert response.status_code == 201, response.text
    id = response.json()["id"]
    assert c.put(f"/api/v1/firmware/images/{id}/content", content=CONTENT).status_code == 200
    detail = c.get(f"/api/v1/firmware/images/{id}").json()
    assert detail["release_notes"] == NOTES
    assert detail["notes"] == "BootROM ve kurtarma talimatları"
    statements = []
    with fw["sf"]() as db:
        bind = db.get_bind()

        def capture(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", capture)
        try:
            listing = c.get("/api/v1/firmware/images").json()
        finally:
            event.remove(bind, "before_cursor_execute", capture)
    assert listing["total"] == 2
    assert all("release_notes" not in row for row in listing["items"])
    assert not any("release_notes" in statement for statement in statements)


def test_edit_existing_ready_image_keeps_file_hash_metadata_and_jobs_unchanged(fw):
    c, id = fw["client"], fw["image"]["id"]
    before = c.get(f"/api/v1/firmware/images/{id}").json()
    assert before["release_notes"] == ""
    response = c.patch(f"/api/v1/firmware/images/{id}/release-notes", json={"release_notes": NOTES})
    assert response.status_code == 200, response.text
    after = c.get(f"/api/v1/firmware/images/{id}").json()
    assert after["release_notes"] == NOTES
    assert {k: v for k, v in before.items() if k not in ("release_notes", "updated_at")} == {
        k: v for k, v in after.items() if k not in ("release_notes", "updated_at")
    }
    with fw["sf"]() as db:
        assert image_path(db.get(m.FirmwareImage, id)).read_bytes() == CONTENT
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        audit = db.scalar(select(m.Audit).where(m.Audit.entity_id == id).order_by(m.Audit.created_at.desc()))
        assert NOTES not in str(audit.__dict__)


def test_length_validation_and_clearing_notes(fw):
    c, id = fw["client"], fw["image"]["id"]
    path = f"/api/v1/firmware/images/{id}/release-notes"
    assert c.patch(path, json={"release_notes": "x" * 50000}).status_code == 200
    assert c.patch(path, json={"release_notes": "x" * 50001}).status_code == 422
    assert c.patch(path, json={"release_notes": NOTES, "family": "hp1950"}).status_code == 422
    assert c.get(f"/api/v1/firmware/images/{id}").json()["release_notes"] == "x" * 50000
    assert c.patch(path, json={"release_notes": "  "}).status_code == 200
    assert c.get(f"/api/v1/firmware/images/{id}").json()["release_notes"] == ""


def test_viewer_can_read_but_cannot_edit_release_notes(fw):
    c, id = fw["client"], fw["image"]["id"]
    with fw["sf"]() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert c.get(f"/api/v1/firmware/images/{id}").status_code == 200
    assert (
        c.patch(f"/api/v1/firmware/images/{id}/release-notes", json={"release_notes": NOTES}).status_code
        == 403
    )
    c.cookies.clear()
    assert c.get(f"/api/v1/firmware/images/{id}").status_code == 401


def test_missing_image_does_not_create_a_release_note_record(fw):
    c = fw["client"]
    assert c.get("/api/v1/firmware/images/missing").status_code == 404
    assert (
        c.patch("/api/v1/firmware/images/missing/release-notes", json={"release_notes": NOTES}).status_code
        == 404
    )


def test_migration_preserves_old_notes_and_refuses_lossy_downgrade():
    """Exercise additive/default/rollback behavior in an attached local SQLite schema."""
    import importlib.util
    from pathlib import Path

    import pytest
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    path = (
        Path(__file__).resolve().parents[1]
        / "backend/pg_migrations/versions/20261110_02_firmware_release_notes.py"
    )
    spec = importlib.util.spec_from_file_location("release_notes_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS firmware"))
        connection.execute(
            text("CREATE TABLE firmware.firmware_images (id TEXT PRIMARY KEY, notes TEXT NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO firmware.firmware_images VALUES ('existing', 'BootROM instructions')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(
                text("SELECT notes, release_notes FROM firmware.firmware_images")
            ).one() == ("BootROM instructions", "")
            connection.execute(text("UPDATE firmware.firmware_images SET release_notes = 'Keep this note'"))
            with pytest.raises(RuntimeError, match="preserved"):
                migration.downgrade()
            assert (
                connection.scalar(text("SELECT release_notes FROM firmware.firmware_images"))
                == "Keep this note"
            )
            connection.execute(text("UPDATE firmware.firmware_images SET release_notes = ''"))
            migration.downgrade()
            assert (
                connection.scalar(text("SELECT notes FROM firmware.firmware_images"))
                == "BootROM instructions"
            )
