"""Persistent reference configurations and approvals of meaningful configuration state."""

import difflib
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import func, select

from .. import models as m
from ..core import now
from ..identity.security import audit, decrypt
from .diff import cli_lines, config_diff, quote_state, redact_config
from .formatting import config_text
from .validation import BackupError, validate_cli_output

# Only known exporter/version metadata is ignored. Values inside quoted banners
# and arbitrary configuration commands remain significant, including secrets.
METADATA = re.compile(
    r"^\s*(?:#(?:config-version|conf_file_ver|buildno|global_vdom)\s*=|"
    r"conf_file_ver\s*[=:]|!\s*Version AOS-CX\b|"
    r";.*Configuration Editor;.*Created on release)",
    re.I,
)

PREAMBLE = re.compile(
    r"^\s*(?:(?:\S+[#>]\s*)?(?:show (?:running-config|configuration)(?: all)?|"
    r"display current-configuration)|(?:Current|Running) configuration:(?:\s*\d+ bytes)?|"
    r"Building configuration\.\.\.)\s*$",
    re.I,
)


def meaningful(content):
    lines, quoted, header = [], False, True
    for line in config_text(content).replace("\r\n", "\n").splitlines():
        if not quoted and METADATA.match(line):
            continue
        if header and (not line.strip() or PREAMBLE.fullmatch(line)):
            continue
        header = False
        lines.append(line)
        if quoted or not line.lstrip().startswith(("#", "!", ";")):
            quoted = quote_state(line, quoted)
    return "\n".join(lines).rstrip("\n")


def fingerprint(content):
    return hashlib.sha256(meaningful(content).encode()).hexdigest()


def base(db, device):
    row = db.get(m.Snapshot, device.base_snapshot_id) if device.base_snapshot_id else None
    if row and row.device_id == device.id:
        return row
    for row in db.scalars(
        select(m.Snapshot)
        .where(m.Snapshot.device_id == device.id)
        .order_by(m.Snapshot.created_at, m.Snapshot.id)
    ):
        try:
            validate_cli_output(decrypt(row.encrypted_content))
        except BackupError:
            continue
        device.base_snapshot_id = row.id
        return row
    return None


def pending_ids(db):
    latest = select(
        m.Snapshot.id,
        m.Snapshot.device_id,
        m.Snapshot.changed,
        m.Snapshot.fingerprint,
        func.row_number()
        .over(
            partition_by=m.Snapshot.device_id, order_by=(m.Snapshot.created_at.desc(), m.Snapshot.id.desc())
        )
        .label("position"),
    ).subquery()
    return (
        select(latest.c.id)
        .join(m.Device, m.Device.id == latest.c.device_id)
        .where(
            latest.c.position == 1,
            latest.c.changed.is_(True),
            latest.c.fingerprint != m.Device.approved_config_hash,
        )
    )


def rebuild(db, device):
    reference = base(db, device)
    reference_hash = fingerprint(decrypt(reference.encrypted_content)) if reference else None
    for row in db.scalars(select(m.Snapshot).where(m.Snapshot.device_id == device.id)):
        content = decrypt(row.encrypted_content)
        try:
            validate_cli_output(content)
        except BackupError:
            row.changed = False
            continue
        row.fingerprint = fingerprint(content)
        row.changed = bool(reference_hash and row.fingerprint != reference_hash)


def set_base(db, snapshot_id, user):
    from .management import snapshot_text

    row = db.get(m.Snapshot, snapshot_id)
    if not row:
        raise HTTPException(404, "Konfigürasyon bulunamadı")
    device = db.scalar(select(m.Device).where(m.Device.id == row.device_id).with_for_update())
    snapshot_text(row)
    device.base_snapshot_id = row.id
    device.approved_config_hash = ""
    rebuild(db, device)
    audit(db, user, "set_base", "snapshots", row.id, "Base config seçildi")
    db.commit()
    from ..services import publish

    publish()
    return {"base_snapshot_id": row.id}


def approve(db, snapshot_id, user):
    row = db.get(m.Snapshot, snapshot_id)
    if not row:
        raise HTTPException(404, "Konfigürasyon bulunamadı")
    device = db.scalar(select(m.Device).where(m.Device.id == row.device_id).with_for_update())
    if snapshot_id not in set(db.scalars(pending_ids(db))):
        raise HTTPException(409, "Değişiklik güncellendi; son konfigürasyonu yeniden inceleyin")
    device.approved_config_hash = row.fingerprint
    device.config_approved_at, device.config_approved_by = now(), user.id
    audit(db, user, "approve_config", "snapshots", row.id, "Base config farkı onaylandı")
    db.commit()
    from ..services import publish

    publish()
    return {"approved": True}


def comparison(db, ids, *, distinct_devices=False):
    from .management import snapshot_text

    if not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise HTTPException(422, "İki ile dört farklı konfigürasyon seçin")
    rows = [db.get(m.Snapshot, id) for id in ids]
    if any(row is None for row in rows):
        raise HTTPException(404, "Konfigürasyon bulunamadı")
    if distinct_devices and len({row.device_id for row in rows}) != len(rows):
        raise HTTPException(422, "Her konfigürasyon farklı bir cihazdan seçilmeli")
    texts = [meaningful(snapshot_text(row)) for row in rows]
    documents = []
    for index, (row, content) in enumerate(zip(rows, texts, strict=True)):
        lines = content.splitlines()
        safe = (
            redact_config(content).splitlines()
            if content.lstrip().startswith(("{", "[", "<"))
            else cli_lines(content)
        )
        marks = set()
        peers = texts[1:] if index == 0 else texts[:1]
        for peer in peers:
            for tag, start, stop, _, _ in difflib.SequenceMatcher(
                None, lines, peer.splitlines(), autojunk=False
            ).get_opcodes():
                if tag != "equal":
                    marks.update(range(start, stop))
        device = db.get(m.Device, row.device_id)
        documents.append(
            {
                "id": row.id,
                "device_id": row.device_id,
                "device_name": device.name,
                "created_at": row.created_at,
                "is_base": device.base_snapshot_id == row.id,
                "lines": [
                    {"number": n + 1, "text": line, "changed": n in marks} for n, line in enumerate(safe)
                ],
                "diff": config_diff(texts[0], content) if index else "",
            }
        )
    return {"documents": documents, "changed": len(set(texts)) > 1, "redacted": True}
