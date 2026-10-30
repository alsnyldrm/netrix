"""Apply only observed identity fields; missing values never erase managed inventory."""

from sqlalchemy import select

from .. import models as m
from ..discovery.identification import KINDS, normalize


def apply_identity(db, device, fields, job_id, source):
    fields = normalize(fields)
    # Backbone/controller and other catalog extensions are managed classifications,
    # not hardware classes inferred by a protocol. Keep the user's finer distinction.
    if device.kind not in KINDS | {"other", None}:
        fields.pop("kind", None)
    if fields.get("kind") and not db.scalar(
        select(m.DeviceType.id).where(m.DeviceType.code == fields["kind"])
    ):
        fields.pop("kind")
    changes = {}
    for key, value in fields.items():
        old = getattr(device, key)
        if old != value:
            changes[key] = {"previous": old, "current": value}
            setattr(device, key, value)
    if changes:
        db.add(
            m.Event(
                device_id=device.id,
                kind="device_identity_change",
                message=f"{device.name}: cihazdan alınan kimlik bilgileri güncellendi",
                details={"job_id": job_id, "source": source, "changes": changes},
            )
        )
    return fields
