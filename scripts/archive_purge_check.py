"""Exercise archived-device FK deletion on disposable MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.identity.security import encrypt
from netrix.inventory.archive import purge_devices
from sqlalchemy import select

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    vrf = m.VRF(name="Archive fixture")
    user = m.User(email="fixture@example.test", display_name="Fixture", password_hash="unused", role="admin")
    profile = m.Credential(name="shared", protocol="ssh", encrypted_secret=encrypt("{}"))
    db.add_all([vrf, user, profile])
    db.flush()
    device = m.Device(
        name="archived fixture",
        management_ip="192.0.2.1",
        vrf_id=vrf.id,
        archived=True,
        config_credential_id=profile.id,
    )
    peer = m.Device(name="retained", management_ip="192.0.2.2", vrf_id=vrf.id)
    db.add_all([device, peer])
    db.flush()
    port = m.Interface(device_id=device.id, name="1", if_index=1)
    job = m.Job(kind="backup", target_id=device.id, status="queued", active_key="backup:" + device.id)
    vlan = m.VLAN(domain="fixture", name="fixture", vid=99)
    db.add_all([port, job, vlan])
    db.flush()
    snap = m.Snapshot(
        device_id=device.id,
        job_id=job.id,
        encrypted_content=encrypt("secret"),
        fingerprint="fixture",
        size_bytes=6,
    )
    db.add(snap)
    db.flush()
    device.base_snapshot_id = snap.id
    ip = m.IPAddress(
        address=device.management_ip,
        vrf_id=vrf.id,
        vlan_id=vlan.id,
        device_id=device.id,
        interface_id=port.id,
    )
    link = m.Link(
        device_id=peer.id,
        remote_device_id=device.id,
        manual_remote_device_id=device.id,
        interface_name="2",
        remote_name="archived fixture",
        remote_port="1",
    )
    observation = m.Observation(device_id=device.id, job_id=job.id, address=device.management_ip, evidence={})
    event = m.Event(device_id=device.id, kind="fixture", message="history")
    db.add_all([ip, link, observation, event])
    db.commit()
    id, ip_id, peer_id, profile_id = device.id, ip.id, peer.id, profile.id
    purge_devices(db, [device], user)
    db.commit()
    assert db.get(m.Device, id) is None
    assert db.get(m.Device, peer_id) and db.get(m.Credential, profile_id)
    assert db.get(m.IPAddress, ip_id).device_id is None and db.get(m.IPAddress, ip_id).interface_id is None
    assert not list(db.scalars(select(m.Snapshot))) and not list(db.scalars(select(m.Interface)))
    assert not list(db.scalars(select(m.Link))) and not list(db.scalars(select(m.Observation)))
    assert db.scalar(select(m.Event)).device_id is None
    assert db.scalar(select(m.Job)).status == "cancelled"
    assert db.scalar(select(m.Audit)).action == "bulk_purge"
print(
    "MariaDB archive purge PASS: base-config FK, inbound/manual links, IPAM detach, shared records and history retained"
)
