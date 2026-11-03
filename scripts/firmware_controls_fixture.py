"""Control scenarios use a disposable database and no protocol workers."""

from netrix import models as m
from netrix.core import now, session_factory
from sqlalchemy import select

from scripts.firmware_fixture import app  # noqa: F401

with session_factory()() as db:
    image = db.scalar(select(m.FirmwareImage))
    user = db.scalar(select(m.User))
    for index, name in enumerate(("Fixture live control", "Fixture soft control", "Fixture done control")):
        plan = m.FirmwarePlan(
            name=name,
            mode="stage",
            status="succeeded" if index == 2 else "running",
            concurrency=10,
            requested_by=user.id,
            steps=[
                {
                    "group_name": "Control group",
                    "group_id": None,
                    "image_id": image.id,
                    "version": image.version,
                    "count": 3,
                }
            ],
        )
        db.add(plan)
        db.flush()
        for number in range(3):
            device = db.scalar(
                select(m.Device).where(m.Device.name == f"Fixture {800 + index * 3 + number:04}")
            )
            status = "succeeded" if index == 2 else ("running", "staged", "queued")[number]
            target = m.FirmwareTarget(
                plan_id=plan.id,
                device_id=device.id,
                image_id=image.id,
                stage=0,
                status=status,
                phase="transferring" if status == "running" else "waiting",
                active_device=device.id if index != 2 else None,
                evidence={
                    "device_name": device.name,
                    "management_ip": device.management_ip,
                    "expected_version": image.version,
                },
                heartbeat_at=now(),
            )
            db.add(target)
            db.flush()
            db.add(
                m.FirmwareEvent(
                    target_id=target.id,
                    kind="phase",
                    phase=target.phase,
                    title="Fixture retained event",
                    status="info",
                    finished_at=now(),
                )
            )
    db.commit()
