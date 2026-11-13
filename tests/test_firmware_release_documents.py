"""Real document bytes and written release notes remain independent."""

import hashlib
import io
import zipfile
from urllib.parse import quote

import pytest
from netrix import models as m
from netrix.firmware import release_files
from netrix.firmware.service import image_path
from sqlalchemy import event, func, select
from test_firmware import CONTENT
from test_firmware import fw as firmware_fixture

fw = firmware_fixture
PDF = b"%PDF-1.7\nRelease fixture\n%%EOF"
TEXT = "Düzeltmeler\nSSH erişimi".encode()


def docx():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as document:
        document.writestr("[Content_Types].xml", "<Types/>")
        document.writestr("word/document.xml", "<document>Release fixture</document>")
    return stream.getvalue()


def paths(fw):
    base = f"/api/v1/firmware/images/{fw['image']['id']}"
    return base, base + "/release-notes/content"


def put(fw, filename="Sürüm notları.pdf", content=PDF):
    return fw["client"].put(
        paths(fw)[1], content=content, headers={"X-Netrix-Filename": quote(filename, safe="")}
    )


@pytest.mark.parametrize(
    "filename,content", [("Sürüm notları.pdf", PDF), ("notes.docx", docx()), ("notes.txt", TEXT)]
)
def test_document_and_text_can_both_be_saved_without_changing_image(fw, filename, content):
    c = fw["client"]
    base, file_path = paths(fw)
    assert c.patch(base + "/release-notes", json={"release_notes": "Yazılı not"}).status_code == 200
    response = put(fw, filename, content)
    assert response.status_code == 200, response.text
    detail = c.get(base).json()
    assert detail["release_notes"] == "Yazılı not"
    assert detail["release_file"]["filename"] == filename
    assert detail["release_file"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert "content" not in detail["release_file"]
    assert c.patch(base + "/release-notes", json={"release_notes": "Düzenlenen not"}).status_code == 200
    download = c.get(file_path)
    assert download.content == content
    assert download.headers["content-disposition"] == "attachment; filename*=UTF-8''" + quote(
        filename, safe=""
    )
    assert download.headers["x-content-type-options"] == "nosniff"
    with fw["sf"]() as db:
        image = db.get(m.FirmwareImage, fw["image"]["id"])
        assert image.sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert image_path(image).read_bytes() == CONTENT
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0


def test_bad_replacement_keeps_both_saved_values_and_stream_limit_is_enforced(fw, monkeypatch):
    c = fw["client"]
    base, file_path = paths(fw)
    assert put(fw).status_code == 200
    for filename, content in (
        ("wrong.pdf", b"not a PDF"),
        ("../notes.txt", TEXT),
        ("empty.txt", b""),
        ("active.html", TEXT),
    ):
        assert put(fw, filename, content).status_code == 422
    monkeypatch.setattr(release_files, "MAX_BYTES", 40)
    assert put(fw, "long.txt", iter([b"y" * 25, b"z" * 25])).status_code == 413
    assert c.get(file_path).content == PDF
    assert put(fw, "new.txt", TEXT).status_code == 200
    assert c.get(base).json()["release_notes"] == ""
    assert c.get(file_path).content == TEXT


def test_permissions_and_metadata_queries_do_not_read_document_bytes(fw):
    c = fw["client"]
    base, file_path = paths(fw)
    assert c.get(file_path).status_code == 404
    assert put(fw).status_code == 200
    with fw["sf"]() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
        bind = db.get_bind()
        statements = []

        def capture(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", capture)
        try:
            assert c.get(base).status_code == 200
            assert c.get("/api/v1/firmware/images").status_code == 200
        finally:
            event.remove(bind, "before_cursor_execute", capture)
    assert not any("firmware_release_files.content" in statement for statement in statements)
    assert put(fw).status_code == 403
    assert c.get(file_path).content == PDF
    c.cookies.clear()
    assert c.get(file_path).status_code == 401
