"""Disposable saved FortiOS revisions, including settings and header-only changes."""

import hashlib
from datetime import timedelta

from netrix.core import now
from netrix.identity.security import encrypt
from sqlalchemy import select

from scripts import inventory_fixture as fixture

app = fixture.app
with fixture.session_factory()() as db:
    device = db.scalar(select(fixture.m.Device).where(fixture.m.Device.name == "Fixture 00"))
    rows = list(
        db.scalars(
            select(fixture.m.Snapshot)
            .where(fixture.m.Snapshot.device_id == device.id)
            .order_by(fixture.m.Snapshot.created_at, fixture.m.Snapshot.id)
        )
    )
    old = (
        "#config-version=FG-fixture\n#conf_file_ver=1\nconfig system global\n"
        + "".join(f"    set fixture-{i} enable\n" for i in range(15))
        + '    set admintimeout 5\nend\nconfig system admin\n    edit "admin"\n        set password ENC FIXTURE-PRIVATE\n    next\nend\n'
    )
    changed = old.replace("admintimeout 5", "admintimeout 15").replace("FIXTURE-PRIVATE", "CHANGED-PRIVATE")
    job = fixture.m.Job(kind="backup", target_id=device.id, status="succeeded")
    db.add(job)
    db.flush()
    rows.append(fixture.m.Snapshot(device_id=device.id, job_id=job.id))
    for index, (row, content) in enumerate(
        zip(rows, [old, changed, changed.replace("#conf_file_ver=1", "#conf_file_ver=2")], strict=True)
    ):
        row.encrypted_content = encrypt(content)
        row.fingerprint = hashlib.sha256(content.encode()).hexdigest()
        row.size_bytes = len(content)
        row.changed = index > 0
        row.created_at = now() - timedelta(minutes=3 - index)
        db.add(row)
    db.commit()
