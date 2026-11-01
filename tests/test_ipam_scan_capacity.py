import asyncio

from conftest import make_vlan
from netrix import models as m
from netrix.ipam import jobs


async def test_ip_scan_uses_bounded_32_address_batches(env, monkeypatch):
    with env() as db:
        vrf = m.VRF(name="ICMP fixture")
        db.add(vrf)
        db.flush()
        prefix = make_vlan(vrf_id=vrf.id, cidr="192.0.2.0/26")
        db.add(prefix)
        db.flush()
        job = m.Job(kind="ipam_discover", target_id=prefix.id)
        db.add(job)
        db.commit()
        id = job.id
    active = peak = 0
    checked = set()

    async def ping(address):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            checked.add(address)
            await asyncio.sleep(0.01)
            return False
        finally:
            active -= 1

    monkeypatch.setattr(jobs.adapters, "ping", ping)
    result = await jobs.scan(id)
    assert peak == 32 and active == 0
    assert len(checked) == 62 and result["checked"] == result["no_reply"] == 62
    with env() as db:
        assert db.get(m.Job, id).progress == db.get(m.Job, id).total == 62
