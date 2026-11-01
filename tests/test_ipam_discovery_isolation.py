import pytest
from netrix import models as m
from netrix import worker
from netrix.ipam import service
from sqlalchemy import select
from test_ipam_workspace import prefix


def evidence(db, vrf):
    device = m.Device(name="Gateway", management_ip="192.0.2.254", vrf_id=vrf)
    db.add(device)
    db.flush()
    job = m.Job(kind="discovery", target_id=device.id, status="succeeded")
    db.add(job)
    db.flush()
    db.add(
        m.Observation(
            device_id=device.id,
            job_id=job.id,
            address=device.management_ip,
            evidence={
                "tables": {
                    "arp_mac": {"1.192.0.2.1": "00:11:22:33:44:55", "1.198.51.100.1": "00:11:22:33:44:66"}
                }
            },
        )
    )
    db.commit()
    return device.id


def test_vlan_creation_queues_only_independent_scan(admin_client, inventory, env):
    with env() as db:
        evidence(db, inventory["vrf"]["id"])
    p = prefix(admin_client, inventory)
    with env() as db:
        jobs = list(db.scalars(select(m.Job).where(m.Job.target_id == p["id"])))
        assert len(jobs) == 1 and jobs[0].kind == "ipam_discover"
        assert not list(db.scalars(select(m.IPAddress)))
        assert not hasattr(service, "inventory_observations")


@pytest.mark.asyncio
async def test_deleted_vlan_cancels_pending_scan(admin_client, inventory, env):
    p = prefix(admin_client, inventory)
    with env() as db:
        job_id = db.scalar(select(m.Job.id).where(m.Job.kind == "ipam_discover", m.Job.target_id == p["id"]))
    assert admin_client.delete("/api/v1/vlans/" + p["id"]).status_code == 204
    await worker.execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "cancelled"
        assert not list(db.scalars(select(m.IPAddress)))
