from io import BytesIO

import pytest
from netrix import models as m
from netrix.access.avatars import MAX_UPLOAD, normalize
from PIL import Image, PngImagePlugin
from sqlalchemy import select


def photo(format="PNG"):
    output = BytesIO()
    image = Image.new("RGB", (320, 180), "#5841be")
    if format == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private", "PRIVATE-UPLOAD-METADATA")
        image.save(output, format=format, pnginfo=metadata)
    else:
        image.save(output, format=format)
    return output.getvalue()


def test_avatar_requires_session(client):
    for method, path in [("get", ""), ("get", "/image"), ("put", ""), ("post", ""), ("delete", "")]:
        assert getattr(client, method)("/api/v1/access/avatar" + path).status_code == 401


def test_preset_photo_persistence_reset_and_audit(admin_client, env):
    c = admin_client
    base = "/api/v1/access/avatar"
    initial = c.get(base).json()
    assert initial["url"] is None
    assert len(initial["presets"]) == 10
    assert c.put(base, json={"preset_id": "../../secrets"}).status_code == 422
    selected = c.put(base, json={"preset_id": "naruto"}).json()
    assert selected["url"] == "/avatars/naruto.png"
    assert c.get(base).json() == selected
    uploaded = c.post(base, content=photo(), headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["preset_id"] is None
    response = c.get(uploaded.json()["url"])
    assert response.headers["content-type"] == "image/webp"
    assert "no-store" in response.headers["cache-control"]
    assert b"PRIVATE-UPLOAD-METADATA" not in response.content
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (256, 256)
        assert not image.getexif()
    old_url = uploaded.json()["url"]
    assert (
        c.post(base, content=photo("JPEG"), headers={"Content-Type": "image/jpeg"}).json()["url"] != old_url
    )
    c.post("/api/v1/auth/logout")
    c.post(
        "/api/v1/auth/login",
        json={"email": "alisan.yildirim@fbu.edu.tr", "password": "test-only-password-long"},
    )
    assert c.get(base).json()["url"] is not None
    assert c.put(base, json={"preset_id": "levi"}).status_code == 200
    assert c.get(base + "/image").status_code == 404
    with env() as db:
        row = db.scalar(select(m.UserAvatar))
        assert row.image is None and row.preset_id == "levi"
        logs = db.scalars(select(m.Audit).where(m.Audit.action == "profile.avatar.update")).all()
        assert len(logs) == 4
        assert all("PRIVATE-UPLOAD" not in str(log.details) for log in logs)
    assert c.delete(base).json()["url"] is None
    assert c.delete(base).status_code == 200


def test_viewer_owns_only_own_avatar(admin_client):
    c = admin_client
    base = "/api/v1/access/avatar"
    c.post(base, content=photo(), headers={"Content-Type": "image/png"})
    owner_url = c.get(base).json()["url"]
    c.post(
        "/api/v1/users",
        json={
            "email": "viewer@example.test",
            "display_name": "Viewer",
            "password": "viewer-avatar-password",
            "role": "viewer",
        },
    )
    c.post("/api/v1/auth/logout")
    c.post("/api/v1/auth/login", json={"email": "viewer@example.test", "password": "viewer-avatar-password"})
    assert c.get(owner_url).status_code == 404
    assert c.get(base).json()["url"] is None
    assert c.put(base, json={"preset_id": "luffy"}).status_code == 200
    assert c.post(base, content=photo(), headers={"Content-Type": "image/png"}).status_code == 200
    assert c.delete(base).status_code == 200
    c.post("/api/v1/auth/logout")
    c.post(
        "/api/v1/auth/login",
        json={"email": "alisan.yildirim@fbu.edu.tr", "password": "test-only-password-long"},
    )
    assert c.get(base).json()["url"] == owner_url
    assert c.get(owner_url).status_code == 200


@pytest.mark.parametrize(
    "data,mime,status",
    [
        (b"<svg></svg>", "image/svg+xml", 415),
        (b"invalid", "image/png", 422),
        (b"x" * (MAX_UPLOAD + 1), "image/png", 413),
        (photo("JPEG"), "image/png", 422),
    ],
)
def test_invalid_upload_keeps_selection(admin_client, data, mime, status):
    c = admin_client
    base = "/api/v1/access/avatar"
    c.put(base, json={"preset_id": "naruto"})
    response = c.post(base, content=data, headers={"Content-Type": mime})
    assert response.status_code == status
    assert c.get(base).json()["preset_id"] == "naruto"


def test_pixel_limit_and_animation():
    from fastapi import HTTPException

    large = BytesIO()
    Image.new("RGB", (4001, 4000)).save(large, format="PNG")
    with pytest.raises(HTTPException):
        normalize(large.getvalue(), "image/png")
    animated = BytesIO()
    Image.new("RGB", (2, 2), "red").save(
        animated, format="PNG", save_all=True, append_images=[Image.new("RGB", (2, 2), "blue")]
    )
    with pytest.raises(HTTPException):
        normalize(animated.getvalue(), "image/png")
