"""New VLANs queue one durable first scan; metadata writes and reads remain passive."""

from conftest import vlan_payload
from fastapi import HTTPException
from netrix import models as m
from netrix import services
from sqlalchemy import func, select


def test_creation_queues_first_scan_atomically_and_reuses_active_job(
    admin_client, inventory, env, monkeypatch
):
    from netrix.ipam import adapters

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP creation must not query the network")

    for name in ("ping", "reverse_dns", "vcenter_records", "windows_dhcp"):
        monkeypatch.setattr(adapters, name, forbidden)
    payload = vlan_payload({"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]})
    response = admin_client.post("/api/v1/vlans", json=payload)
    assert response.status_code == 201, response.text
    vlan = response.json()
    assert vlan["scan"]["status"] == "queued"
    with env() as db:
        jobs = list(db.scalars(select(m.Job)))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == vlan["scan"]["job_id"] and job.target_id == vlan["id"]
        assert job.kind == "ipam_discover" and job.status == "queued"
        assert job.result["ipam_origin"] == "vlan_create" and job.requested_by
    manual = admin_client.post(f"/api/v1/ipam/vlans/{vlan['id']}/discover")
    assert manual.status_code == 202 and manual.json()["id"] == job.id
    with env() as db:
        assert services.enqueue(db, "ipam_discover", vlan["id"], ipam_origin="schedule").id == job.id
        job = db.get(m.Job, job.id)
        job.status, job.active_key = "succeeded", None
        db.commit()
    for _ in range(2):
        assert (
            admin_client.put(
                f"/api/v1/vlans/{vlan['id']}", json={**payload, "description": "Edit"}
            ).status_code
            == 200
        )
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses").status_code == 200
    address = admin_client.post(
        "/api/v1/addresses", json={"vlan_id": vlan["id"], "vrf_id": vlan["vrf_id"], "address": "192.0.2.1"}
    )
    assert address.status_code == 201
    assert admin_client.post("/api/v1/vlans", json=payload).status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 1
        assert not db.scalar(select(m.IPAMScanGroup.id))


def test_failed_initial_enqueue_rolls_back_new_vlan(admin_client, inventory, env, monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPException(503, "Fixture queue failure")

    monkeypatch.setattr(services, "enqueue", fail)
    payload = vlan_payload({"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]})
    response = admin_client.post("/api/v1/vlans", json=payload)
    assert response.status_code == 503
    with env() as db:
        assert not db.scalar(select(m.VLAN.id))
        assert not db.scalar(select(m.Job.id))


def test_deferred_transaction_rolls_back_vlan_and_first_scan_together(inventory, env):
    with env() as db:
        user = db.scalar(select(m.User))
        payload = vlan_payload({"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]})
        vlan = services.save_resource(db, "vlans", payload, user, commit=False)
        assert db.get(m.Job, vlan["scan"]["job_id"])
        db.rollback()
    with env() as db:
        assert not db.scalar(select(m.VLAN.id))
        assert not db.scalar(select(m.Job.id))


def test_creation_defers_large_address_expansion_to_worker(admin_client, inventory, monkeypatch):
    from netrix.ipam import jobs

    def forbidden(*args, **kwargs):
        raise AssertionError("Scan targets must be expanded in the worker, not HTTP creation")

    monkeypatch.setattr(jobs, "targets", forbidden)
    payload = vlan_payload({"cidr": "10.6.0.0/16", "vrf_id": inventory["vrf"]["id"]})
    response = admin_client.post("/api/v1/vlans", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["scan"]["status"] == "queued"
    assert admin_client.post("/api/v1/vlans", json={**payload, "cidr": "10.8.0.0/15"}).status_code == 422


def test_first_scan_origin_cannot_start_ping_or_independent_integration(admin_client, inventory, env):
    import pytest
    from test_ipam_workspace import integration, prefix

    vlan = prefix(admin_client, inventory)
    config = integration(admin_client, vlan)
    with env() as db:
        user = db.scalar(select(m.User))
        for kind, target in (("ipam_ping", vlan["id"]), ("integration", config["id"])):
            with pytest.raises(HTTPException) as error:
                services.enqueue(db, kind, target, user, ipam_origin="vlan_create")
            assert error.value.status_code == 409
