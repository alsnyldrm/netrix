"""Local simulated port observations only; no device connection or scheduler."""

from fastapi import Depends
from netrix import models as m
from netrix.core import session_factory
from netrix.identity.security import operator
from netrix.worker import sync_interfaces
from sqlalchemy import delete, select

from scripts.inventory_fixture import app


def observe(statuses):
    with session_factory()() as db:
        device = db.scalar(select(m.Device).where(m.Device.name == "Fixture 00").with_for_update())
        job = m.Job(kind="discovery", target_id=device.id)
        db.add(job)
        db.flush()
        sync_interfaces(
            db,
            device,
            {
                "interfaces": [
                    {
                        "name": name,
                        "if_index": i,
                        "oper_status": status,
                        "mac_address": "",
                        "description": "",
                        "speed_bps": 1000000000,
                    }
                    for i, (name, status) in enumerate(statuses.items(), 1)
                ]
            },
            job.id,
        )
        db.commit()


with session_factory()() as db:
    device = db.scalar(select(m.Device).where(m.Device.name == "Fixture 00"))
    db.execute(delete(m.Interface).where(m.Interface.device_id == device.id))
    db.commit()
observe({"port1": "up", "port2": "down", "port3": "unknown", "port4": "down"})


@app.post("/_fixture/ports/{state}")
def change_ports(state: str, user=Depends(operator)):
    observe(
        {
            "port1": "down" if state == "down" else "up",
            "port2": "up",
            "port3": "unknown",
            "port4": "up" if state == "all" else "down",
        }
    )
    return {"observed": True}
