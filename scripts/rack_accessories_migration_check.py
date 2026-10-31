"""Accessory migration and cross-type placement locking in disposable MariaDB only."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.ipam import racks
from netrix.ipam.schemas import PlacementInput, RackAccessoryInput
from sqlalchemy import delete, inspect
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test"
racks.publish = lambda: None


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
migrate("check")
migrate("downgrade", "20261031_17")
assert "rack_accessories" not in inspect(engine()).get_table_names()
migrate("upgrade", "head")
with session_factory()() as db:
    vrf = m.VRF(name="Fixture")
    cabinet = m.Cabinet(name="Fixture", units=12)
    db.add_all([vrf, cabinet])
    db.flush()
    device = m.Device(name="Switch", vrf_id=vrf.id, management_ip="192.0.2.1")
    db.add(device)
    db.commit()
    cabinet_id, device_id = cabinet.id, device.id
    racks.place(db, cabinet_id, PlacementInput(device_id=device_id, start_unit=12, units=1), None)
    racks.save_accessory(db, cabinet_id, RackAccessoryInput(start_unit=11), None)
assert migrate("downgrade", "20261031_17", check=False).returncode != 0
for data in ({"cabinet_id": "missing"}, {"start_unit": 0}, {"units": 61}, {"kind": "other"}):
    try:
        with engine().begin() as db:
            db.execute(
                m.RackAccessory.__table__.insert().values(
                    id="bad",
                    created_at=now(),
                    updated_at=now(),
                    **{
                        "cabinet_id": cabinet_id,
                        "kind": "brush_organizer",
                        "start_unit": 1,
                        "units": 1,
                        **data,
                    },
                )
            )
    except DBAPIError as error:
        assert error.orig.args[0] in (1452, 4025), error
    else:
        raise AssertionError(data)
barrier = Barrier(2)


def compete(accessory):
    with session_factory()() as db:
        barrier.wait(timeout=10)
        try:
            if accessory:
                racks.save_accessory(db, cabinet_id, RackAccessoryInput(start_unit=5), None)
            else:
                racks.place(db, cabinet_id, PlacementInput(device_id=device_id, start_unit=5, units=1), None)
            return 200
        except HTTPException as e:
            db.rollback()
            return e.status_code


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete, (True, False))) == [200, 409]
with session_factory()() as db:
    assert db.get(m.Device, device_id)
    db.execute(delete(m.RackAccessory))
    db.commit()
migrate("downgrade", "20261031_17")
migrate("upgrade", "head")
migrate("check")
assert "ix_rack_accessories_cabinet_id" in {
    i["name"] for i in inspect(engine()).get_indexes("rack_accessories")
}
print(
    "MariaDB accessories PASS: guarded roundtrip, FK/CHECK/index, existing device preservation, concurrent device/organizer collision lock"
)
