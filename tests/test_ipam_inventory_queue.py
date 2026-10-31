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
    job = m.Job(kind="monitor", target_id=device.id, status="succeeded")
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


def test_prefix_save_does_not_replay_inventory_inline(admin_client, inventory, env, monkeypatch):
    with env() as db:
        evidence(db, inventory["vrf"]["id"])
    calls = []
    monkeypatch.setattr(service, "inventory_observations", lambda *args: calls.append(True))
    p = prefix(admin_client, inventory)
    assert not calls, "Prefix save blocks on inventory replay"
    with env() as db:
        jobs = list(db.scalars(select(m.Job).where(m.Job.kind == "ipam_inventory")))
        assert len(jobs) == 1 and jobs[0].target_id == p["id"] and jobs[0].status == "queued"
        assert not list(db.scalars(select(m.IPAddress)))


@pytest.mark.asyncio
async def test_cached_inventory_job_only_imports_target_prefix_and_retries_safely(
    admin_client, inventory, env
):
    with env() as db:
        evidence(db, inventory["vrf"]["id"])
    p = prefix(admin_client, inventory)
    with env() as db:
        db.add(m.Prefix(cidr="198.51.100.0/24", vrf_id=p["vrf_id"]))
        db.commit()
        job_id = db.scalar(select(m.Job.id).where(m.Job.kind == "ipam_inventory", m.Job.target_id == p["id"]))
    assert job_id
    await worker.execute(job_id)
    await worker.execute(job_id)
    with env() as db:
        assert [(r.address, r.prefix_id) for r in db.scalars(select(m.IPAddress))] == [("192.0.2.1", p["id"])]
        assert len(list(db.scalars(select(m.IPObservation)))) == 1
        assert db.get(m.Job, job_id).status == "succeeded"


@pytest.mark.asyncio
async def test_deleted_prefix_cancels_pending_inventory_job(admin_client, inventory, env):
    p = prefix(admin_client, inventory)
    with env() as db:
        job_id = db.scalar(select(m.Job.id).where(m.Job.kind == "ipam_inventory", m.Job.target_id == p["id"]))
    assert job_id
    assert admin_client.delete("/api/v1/prefixes/" + p["id"]).status_code == 204
    await worker.execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "cancelled"
        assert not list(db.scalars(select(m.IPAddress)))


@pytest.mark.asyncio
async def test_inventory_respects_child_block_and_stale_snapshots(admin_client, inventory, env):
    from datetime import timedelta

    from netrix.core import now

    with env() as db:
        evidence(db, inventory["vrf"]["id"])
        db.add(m.Prefix(cidr="192.0.2.0/30", vrf_id=inventory["vrf"]["id"]))
        db.commit()
    p = prefix(admin_client, inventory, "192.0.2.0/24")
    with env() as db:
        job_id = db.scalar(select(m.Job.id).where(m.Job.kind == "ipam_inventory", m.Job.target_id == p["id"]))
    await worker.execute(job_id)
    with env() as db:
        assert [r.address for r in db.scalars(select(m.IPAddress))] == ["192.0.2.254"]
        old = db.scalar(select(m.Observation))
        old.created_at = now() - timedelta(hours=25)
        db.commit()
    from netrix.ipam.inventory_sync import cached_records

    assert len(cached_records(old.device_id, p["vrf_id"], p["cidr"])) == 1


@pytest.mark.asyncio
async def test_inventory_cancellation_between_small_transactions(admin_client, inventory, env, monkeypatch):
    from netrix.ipam import inventory_sync

    with env() as db:
        evidence(db, inventory["vrf"]["id"])
        db.scalar(select(m.Observation)).evidence = {
            "tables": {"arp_mac": {f"1.192.0.2.{i}": "00:11:22:33:44:55" for i in range(1, 25)}}
        }
        db.commit()
    p = prefix(admin_client, inventory, "192.0.2.0/24")
    with env() as db:
        job_id = db.scalar(select(m.Job.id).where(m.Job.kind == "ipam_inventory", m.Job.target_id == p["id"]))
    original = inventory_sync.persist_batch

    def cancel_after_batch(*args):
        count = original(*args)
        with env() as db:
            db.get(m.Job, job_id).cancel_requested = True
            db.commit()
        return count

    monkeypatch.setattr(inventory_sync, "persist_batch", cancel_after_batch)
    await worker.execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "cancelled"
        assert len(list(db.scalars(select(m.IPAddress)))) == 8
