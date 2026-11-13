"""Optional release documents; firmware bytes and written notes are independent."""

import asyncio
import hashlib
import io
import re
import zipfile
from pathlib import PurePath
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import models as m
from ..core import db_session
from ..identity.security import admin, audit, current_user
from ..services import get, publish

MAX_BYTES = 20 * 1024 * 1024
TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_slots = asyncio.Semaphore(4)
router = APIRouter()


def metadata(db, image_id):
    file = m.FirmwareReleaseFile
    row = db.execute(
        select(file.filename, file.media_type, file.size_bytes, file.sha256).where(file.image_id == image_id)
    ).one_or_none()
    return dict(row._mapping) if row else None


def validate(filename, content):
    if not filename or len(filename) > 180 or re.search(r"[\x00-\x1f\x7f/\\]", filename):
        raise HTTPException(422, "Release belgesinin dosya adı geçersiz")
    extension = PurePath(filename).suffix.lower()
    if extension not in TYPES:
        raise HTTPException(422, "PDF, DOCX veya UTF-8 TXT belgesi seçin")
    if not content:
        raise HTTPException(422, "Release belgesi boş olamaz")
    valid = False
    if extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension == ".txt":
        try:
            value = content.decode("utf-8-sig")
            valid = bool(value.strip()) and not re.search(r"[\x00-\x08\x0b\x0e-\x1f]", value)
        except UnicodeDecodeError:
            pass
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                valid = (
                    {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist())
                    and sum(info.file_size for info in entries) <= 100 * 1024 * 1024
                    and not any(
                        info.flag_bits & 1 or "vbaproject" in info.filename.lower() for info in entries
                    )
                )
        except (zipfile.BadZipFile, ValueError):
            pass
    if not valid:
        raise HTTPException(422, "Belge içeriği dosya biçimiyle eşleşmiyor")
    return TYPES[extension]


def save(db, id, filename, content, user):
    media_type = validate(filename, content)
    if not db.scalar(
        select(m.FirmwareImage.id).where(m.FirmwareImage.id == id).with_for_update(of=m.FirmwareImage)
    ):
        raise HTTPException(404, "Firmware imajı bulunamadı")
    row = db.get(m.FirmwareReleaseFile, id)
    if row is None:
        row = m.FirmwareReleaseFile(image_id=id)
        db.add(row)
    row.filename, row.media_type, row.size_bytes = filename, media_type, len(content)
    row.content, row.sha256 = content, hashlib.sha256(content).hexdigest()
    audit(db, user, "upload", "firmware_images", id, "Firmware release belgesi yüklendi")
    db.commit()
    publish()
    return metadata(db, id)


@router.put("/images/{id}/release-notes/content")
async def upload(id: str, request: Request, db=Depends(db_session), user=Depends(admin)):
    get(db, m.FirmwareImage, id)
    db.commit()
    try:
        length = int(request.headers.get("content-length", "0"))
        filename = unquote(request.headers.get("x-netrix-filename", ""), errors="strict").strip()
    except ValueError:
        raise HTTPException(422, "Belge bilgileri geçersiz") from None
    if length < 0 or length > MAX_BYTES:
        raise HTTPException(413, "Release belgesi en fazla 20 MB olabilir")
    if _slots.locked():
        raise HTTPException(429, "Dört release belgesi yükleniyor; tamamlanmasını bekleyin")
    async with _slots:
        content = bytearray()
        try:
            async with asyncio.timeout(120):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise HTTPException(413, "Release belgesi en fazla 20 MB olabilir")
                    content.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Belge yüklemesi zaman aşımına uğradı") from None
        return await run_in_threadpool(save, db, id, filename, bytes(content), user)


@router.get("/images/{id}/release-notes/content")
def download(id: str, db=Depends(db_session), user=Depends(current_user)):
    file = m.FirmwareReleaseFile
    row = db.execute(
        select(file.filename, file.media_type, file.content).where(file.image_id == id)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Release belgesi bulunamadı")
    return Response(
        row.content,
        media_type=row.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )
