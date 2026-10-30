"""Round-trip and query validation on disposable MariaDB netrix_test only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.inventory.management import query

assert engine().url.database == "netrix_test"
with session_factory()() as db:
    vrf = m.VRF(name="inventory-roundtrip")
    site = m.Site(name="Kuzey", code="INV")
    db.add_all([vrf, site])
    db.flush()
    device = m.Device(
        name="Legacy",
        management_ip="192.0.2.251",
        vrf_id=vrf.id,
        site_id=site.id,
        kind="firewall",
        vendor="Retained",
        ssh_trust_host_key=True,
    )
    db.add(device)
    db.flush()
    port = m.Interface(device_id=device.id, name="port1", if_index=1, speed_bps=1000000000, oper_status="up")
    db.add(port)
    db.commit()
    device_id, port_id, vrf_id, site_id = device.id, port.id, vrf.id, site.id
for args in (["downgrade", "20261030_04"], ["upgrade", "head"], ["check"]):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=True)
with session_factory()() as db:
    device = db.get(m.Device, device_id)
    port = db.get(m.Interface, port_id)
    assert device.vendor == "Retained" and device.ssh_trust_host_key and not device.archived
    assert port.is_managed and port.monitoring_enabled and not port.is_deleted
    for resource, term in (
        ("devices", "Kuzey"),
        ("devices", "Aktif"),
        ("interfaces", "1 Gbps"),
        ("interfaces", "Firewall"),
    ):
        assert query(db, resource, q=term)["total"] == 1, (resource, term)
    group = m.BackupGroup(name="Group", interval_seconds=900, retention_count=5)
    db.add(group)
    db.flush()
    device.backup_group_id = group.id
    db.commit()
    row = query(db, "devices")["items"][0]
    assert row["effective_backup_interval"] == 900 and row["effective_retention"] == 5
    db.delete(port)
    db.flush()
    db.delete(device)
    db.flush()
    db.delete(group)
    db.delete(db.get(m.VRF, vrf_id))
    db.delete(db.get(m.Site, site_id))
    db.commit()
print(
    "MariaDB inventory migration PASS: legacy preservation, selected ports, schema, joined searches, capacity, effective group policy"
)
