"""Migration round trip only on a disposable netrix_test database."""

import subprocess
from uuid import uuid4

from netrix import models as m
from netrix.core import engine, session_factory

assert engine().url.database == "netrix_test", "Dedicated test database required"
with session_factory()() as db:
    vrf = m.VRF(name="ssh-trust-migration-" + uuid4().hex[:8])
    db.add(vrf)
    db.flush()
    device = m.Device(
        name="Migration fixture",
        management_ip="192.0.2.254",
        vrf_id=vrf.id,
        vendor="Manual vendor",
        model="Manual model",
        kind="router",
        config_port=1234,
        ssh_trust_host_key=True,
    )
    db.add(device)
    db.commit()
    device_id, vrf_id = device.id, vrf.id
for args in (["downgrade", "20261030_03"], ["upgrade", "head"], ["check"]):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=True)
with session_factory()() as db:
    device = db.get(m.Device, device_id)
    assert device.ssh_trust_host_key is False
    assert (device.vendor, device.model, device.kind, device.config_port) == (
        "Manual vendor",
        "Manual model",
        "router",
        1234,
    )
    device.ssh_trust_host_key = True
    db.commit()
    db.expire_all()
    assert db.get(m.Device, device_id).ssh_trust_host_key is True
    db.delete(device)
    db.flush()
    db.delete(db.get(m.VRF, vrf_id))
    db.commit()
print("MariaDB SSH trust migration PASS: round trip, schema, existing data, default false, persistence")
