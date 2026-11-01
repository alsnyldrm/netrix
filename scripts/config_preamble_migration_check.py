"""Verify command-echo normalization and approval preservation on disposable MariaDB."""

import hashlib
import subprocess
from datetime import timedelta

from netrix import models as m
from netrix.configuration.baselines import pending_ids
from netrix.core import engine, now, session_factory
from netrix.identity.security import encrypt

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "20261101_21"], check=True)
with session_factory()() as db:
    vrf = m.VRF(name="Preamble fixture")
    db.add(vrf)
    db.flush()
    for index in range(2):
        device = m.Device(
            id=f"preamble-device-{index}",
            name=f"Fixture {index}",
            management_ip=f"192.0.2.{index + 1}",
            vrf_id=vrf.id,
        )
        db.add(device)
        db.flush()
        for version in range(2):
            content = "Current configuration:\n!\nhostname fixture\ninterface 1\n description original"
            if version:
                content = "show running-config\n" + content
                if index:
                    content = content.replace("original", "actual-change")
            job = m.Job(kind="backup", target_id=device.id)
            db.add(job)
            db.flush()
            row = m.Snapshot(
                id=f"preamble-{index}-{version}",
                device_id=device.id,
                job_id=job.id,
                encrypted_content=encrypt(content),
                fingerprint=hashlib.sha256(content.encode()).hexdigest(),
                size_bytes=len(content),
                changed=bool(version),
                created_at=now() + timedelta(minutes=version),
            )
            db.add(row)
            db.flush()
            if not version:
                device.base_snapshot_id = row.id
            elif index:
                device.approved_config_hash = row.fingerprint
    db.commit()
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    assert not db.get(m.Snapshot, "preamble-0-1").changed
    row = db.get(m.Snapshot, "preamble-1-1")
    assert row.changed
    assert db.get(m.Device, row.device_id).approved_config_hash == row.fingerprint
    assert list(db.scalars(pending_ids(db))) == []
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print("PASS: echoed commands ignored, genuine changes retained, approvals preserved")
