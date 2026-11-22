"""Blacklist fixture with seeded sync states (no workers, no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from blacklist_fixture import app  # noqa: F401
from netrix import models as m
from netrix.core import now, session_factory
from sqlalchemy import select

with session_factory()() as db:
    devices = {d.name: d for d in db.scalars(select(m.Device))}
    user = db.scalar(select(m.User))
    g1 = m.ACLGroup(name="Kampüs çekirdek", profiles={"aos_switch": {"type": "extended", "name": "NETRIX_BL", "number": None}, "aos_cx": {"type": "ipv4", "name": "NETRIX_BL", "number": None}}, status="active")
    g2 = m.ACLGroup(name="Uzak binalar", profiles={"aos_switch": {"type": "extended", "name": "NETRIX_BL", "number": None}}, status="active")
    db.add_all([g1, g2])
    db.flush()
    for name in ("Fixture 5412", "Fixture 2930", "Fixture 6100"):
        db.add(m.ACLGroupDevice(group_id=g1.id, device_id=devices[name].id))
    db.add(m.ACLGroupDevice(group_id=g2.id, device_id=devices["Fixture 5406"].id))
    specs = [
        ("198.51.100.10", "active", "Port tarama kaynağı", [g1]),
        ("198.51.100.11", "active", "", [g1, g2]),
        ("198.51.100.12", "draft", "İnceleme bekliyor", [g2]),
        ("198.51.100.13", "disabled", "", [g1]),
        ("203.0.113.40", "deleting", "Yanlış alarm", [g1]),
        ("203.0.113.41", "active", "Süreli engel", [g2]),
    ]
    for address, status, desc, groups in specs:
        e = m.BlacklistEntry(address=address, status=status, description=desc, updated_by=user.id)
        if address == "203.0.113.41":
            from datetime import timedelta
            e.expires_at = now() + timedelta(days=3)
        db.add(e)
        db.flush()
        for g in groups:
            db.add(m.BlacklistEntryGroup(entry_id=e.id, group_id=g.id))
    prof = g1.profiles["aos_switch"]
    db.add(m.DeviceACLState(device_id=devices["Fixture 5412"].id, profile=prof, addresses=["198.51.100.10", "198.51.100.11", "203.0.113.40"], group_ids=[g1.id], status="synced", verified_at=now()))
    db.add(m.DeviceACLState(device_id=devices["Fixture 2930"].id, profile=prof, addresses=["198.51.100.10", "198.51.100.11"], group_ids=[g1.id], status="synced", verified_at=now()))
    db.add(m.DeviceACLState(device_id=devices["Fixture 6100"].id, profile=g1.profiles["aos_cx"], addresses=["198.51.100.10"], group_ids=[g1.id], status="dirty", attempted={"profile": g1.profiles["aos_cx"], "addresses": ["198.51.100.10", "198.51.100.11"], "group_ids": [g1.id]}))
    job = m.Job(kind="blacklist_send", target_id=devices["Fixture 6100"].id, requested_by=user.id, status="failed", error="6100 portunda başka ACL var; mevcut politika korunarak işlem durduruldu.", result={"phase": "applying", "ports": []}, finished_at=now())
    db.add(job)
    db.flush()
    db.add(m.BlacklistDelivery(entry_id=None, device_id=devices["Fixture 6100"].id, job_id=job.id, payload={"endpoint": [], "reason": "entry"}))
    db.commit()
