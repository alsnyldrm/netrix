"""Device-type migration and concurrent IPAM placement in disposable MariaDB only."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.ipam import racks
from netrix.ipam.schemas import IPPlacementInput
from sqlalchemy import func, select

assert engine().url.database == "netrix_test"
racks.publish = lambda: None


def migrate(*args):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    kinds = {t.code: t.name for t in db.scalars(select(m.DeviceType))}
    assert kinds["storage"] == "Storage" and kinds["san_switch"] == "SAN Switch"
    db.scalar(select(m.DeviceType).where(m.DeviceType.code == "storage")).name = "Storage Custom"
    vrf = m.VRF(name="Fixture")
    cabinet = m.Cabinet(name="04", units=42)
    db.add_all([vrf, cabinet])
    db.flush()
    prefix = m.Prefix(vrf_id=vrf.id, cidr="192.0.2.0/24")
    db.add(prefix)
    db.flush()
    address = m.IPAddress(vrf_id=vrf.id, prefix_id=prefix.id, address="192.0.2.65")
    db.add(address)
    db.commit()
    cabinet_id, address_id = cabinet.id, address.id
barrier = Barrier(2)


def place(_):
    with session_factory()() as db:
        barrier.wait(timeout=10)
        result = racks.place_from_ip(
            db,
            cabinet_id,
            IPPlacementInput(address_id=address_id, name="SV-ID-01", kind="server", start_unit=1, units=2),
            None,
        )
        return result["selected_device_id"]


with ThreadPoolExecutor(max_workers=2) as pool:
    assert len(set(pool.map(place, range(2)))) == 1
with session_factory()() as db:
    assert db.scalar(select(func.count()).select_from(m.Device)) == 1
    assert db.scalar(select(func.count()).select_from(m.RackPlacement)) == 1
    assert db.scalar(select(func.count()).select_from(m.Job)) == 0
migrate("downgrade", "20261031_18")
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    assert db.scalar(select(m.DeviceType).where(m.DeviceType.code == "storage")).name == "Storage Custom"
    assert db.scalar(select(func.count()).select_from(m.Device)) == 1
print(
    "MariaDB IP placement PASS: type seeds, rename preservation, nondestructive roundtrip, concurrent reuse of one device/placement, no scan jobs"
)
