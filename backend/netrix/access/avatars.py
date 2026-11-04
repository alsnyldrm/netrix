"""Account-owned portraits; uploads never become public static files."""

import warnings
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import models as m
from ..core import db_session
from ..identity.security import audit, current_user
from .service import lock_owner

router = APIRouter(prefix="/api/v1/access/avatar", tags=["User workspace & SSH"])
PRESETS = {
    "naruto": "Naruto Uzumaki",
    "luffy": "Monkey D. Luffy",
    "levi": "Levi Ackerman",
    "lelouch": "Lelouch Lamperouge",
    "lawliet": "L Lawliet",
    "zoro": "Roronoa Zoro",
    "killua": "Killua Zoldyck",
    "okabe": "Rintarou Okabe",
    "light": "Light Yagami",
    "edward": "Edward Elric",
}
MAX_UPLOAD = 5 * 1024 * 1024
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def portrait(db, user):
    row = db.get(m.UserAvatar, user.id)
    return {
        "preset_id": row.preset_id if row else None,
        "url": (
            f"/avatars/{row.preset_id}.png"
            if row and row.preset_id
            else f"/api/v1/access/avatar/image?v={row.version}"
            if row
            else None
        ),
        "presets": [{"id": key, "name": name, "url": f"/avatars/{key}.png"} for key, name in PRESETS.items()],
    }


def save(db, user, *, preset_id=None, image=None):
    lock_owner(db, user)
    row = db.get(m.UserAvatar, user.id)
    if row is None:
        row = m.UserAvatar(user_id=user.id)
        db.add(row)
    row.preset_id, row.image, row.version = preset_id, image, m.uid()
    audit(db, user, "profile.avatar.update", "users", user.id, "Profil görseli güncellendi")
    db.commit()
    return portrait(db, user)


def normalize(data: bytes, content_type: str) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if (
                    source.format != FORMATS[content_type]
                    or source.width * source.height > 16_000_000
                    or getattr(source, "is_animated", False)
                ):
                    raise ValueError()
                source.load()
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"), (256, 256))
                # A fresh pixel-only image discards EXIF, ICC and other upload metadata.
                clean = Image.new("RGBA", image.size)
                clean.paste(image)
                output = BytesIO()
                clean.save(output, format="WEBP", quality=85, method=4)
                result = output.getvalue()
                if len(result) > 65535:
                    raise ValueError()
                return result
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            422, "Geçerli, hareketsiz bir JPG, PNG veya WebP seçin (en çok 16 megapiksel)."
        ) from None


@router.get("")
def get_avatar(user=Depends(current_user), db=Depends(db_session)):
    return portrait(db, user)


class Preset(BaseModel):
    preset_id: str


@router.put("")
def select_avatar(payload: Preset, user=Depends(current_user), db=Depends(db_session)):
    if payload.preset_id not in PRESETS:
        raise HTTPException(422, "Listeden bir anime avatarı seçin.")
    return save(db, user, preset_id=payload.preset_id)


@router.post("")
async def upload_avatar(request: Request, user=Depends(current_user), db=Depends(db_session)):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in FORMATS:
        raise HTTPException(415, "JPG, PNG veya WebP dosyası seçin.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD:
            raise HTTPException(413, "Fotoğraf en çok 5 MB olabilir.")
        data.extend(chunk)
    image = await run_in_threadpool(normalize, bytes(data), content_type)
    return save(db, user, image=image)


@router.get("/image")
def get_image(user=Depends(current_user), db=Depends(db_session)):
    row = db.get(m.UserAvatar, user.id)
    if row is None or row.image is None:
        raise HTTPException(404, "Profil fotoğrafı bulunamadı.")
    return Response(row.image, media_type="image/webp", headers={"Cache-Control": "private, no-store"})


@router.delete("")
def remove_avatar(user=Depends(current_user), db=Depends(db_session)):
    lock_owner(db, user)
    row = db.get(m.UserAvatar, user.id)
    if row:
        db.delete(row)
        audit(db, user, "profile.avatar.delete", "users", user.id, "Profil görseli kaldırıldı")
        db.commit()
    return portrait(db, user)
