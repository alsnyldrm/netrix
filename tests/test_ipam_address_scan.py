"""Manual SQL-only address job admission and scope validation."""

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import services
from netrix.ipam import service
from sqlalchemy import func, select
from test_ipam_source_contract import network as network

MAC = "00:11:22:33:44:66"


@pytest.mark.parametrize("ip", ["198.51.100.10", "192.0.2.0", "192.0.2.255"])
def test_rejects_outside_network_and_non_host_targets(admin_client, network, ip):
    sf, _, id, _ = network
    with sf() as db:
        db.get(m.IPAddress, id).address = ip
        db.commit()
    assert admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").status_code == 422


def address(network):
    sf, _, id, _ = network
    with sf() as db:
        return service.enrich(db, [db.get(m.IPAddress, id)])[0]


def test_queue_requires_manual_actor_and_reads_never_start_work(admin_client, network):
    sf, _, id, _ = network
    for _ in range(3):
        assert admin_client.get(f"/api/v1/ipam/addresses/{id}/scan").json() is None
        assert admin_client.get(f"/api/v1/ipam/addresses/{id}").status_code == 200
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 1
        for origin in (None, "schedule", "ping_timer", "vlan_create", "manual"):
            with pytest.raises(HTTPException) as error:
                services.enqueue(db, "ipam_address_scan", id, ipam_origin=origin)
            assert error.value.status_code == 409
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").status_code == 403
    with sf() as db:
        db.scalar(select(m.User)).role = "operator"
        db.commit()
    queued = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan")
    assert queued.status_code == 202
    job = queued.json()
    assert job["kind"] == "ipam_address_scan" and job["total"] == 1
    assert job["result"]["ipam_origin"] == "manual" and job["requested_by"]
    assert job["result"]["address_scope"] == [
        "192.0.2.10",
        address(network)["vrf_id"],
        address(network)["vlan_id"],
    ]
    assert admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()["id"] == job["id"]
    assert admin_client.get(f"/api/v1/ipam/addresses/{id}/scan").json()["id"] == job["id"]
    detail = admin_client.get(f"/api/v1/jobs/{job['id']}").json()
    assert "192.0.2.10" in str(detail)
