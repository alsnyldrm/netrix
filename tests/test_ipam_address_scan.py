"""One explicit IP probe; scoped source writes never alter another address or shared snapshots."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import services, worker
from netrix.ipam import adapters, service
from netrix.ipam.address_scan import NETWORK_SOURCE
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


async def test_worker_probes_one_ip_and_isolates_all_source_changes(admin_client, network, monkeypatch):
    from netrix.ipam import pipeline

    sf, vlan_id, id, ids = network
    with sf() as db:
        other = service.observe(
            db, db.get(m.VLAN, vlan_id), "192.0.2.11", "dns", "system", {"hostname": "unchanged.example"}
        )
        db.commit()
        other_id = other.id
        before = service.enrich(db, [other])[0]
        shared = [(o.id, deepcopy(o.evidence)) for o in db.scalars(select(m.Observation))]
    calls = []

    class Sources:
        async def gateway(self, address):
            calls.append(("gateway", address))
            return {"mac_address": MAC}

        async def vmware(self, address, mac):
            return [
                {
                    "address": address,
                    "vm_id": "vm1",
                    "nic_key": "1",
                    "mac_address": mac,
                    "hostname": "target.example",
                    "operating_system": "Target OS",
                    "dvswitch_name": "DS-TARGET",
                    "dvport": "89",
                }
            ]

        async def physical(self, *_):
            raise AssertionError("No physical queries for VM")

        async def dns(self, *_):
            raise AssertionError("No DNS queries for VM")

        async def dhcp(self, *_):
            raise AssertionError("No DHCP queries for VM")

    async def ping(address):
        calls.append(("ping", address))
        return True

    monkeypatch.setattr(pipeline, "sources_for", lambda *a: Sources())
    monkeypatch.setattr(adapters, "ping", ping)
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], object())
    assert calls == [("gateway", "192.0.2.10"), ("ping", "192.0.2.10")]
    item = address(network)
    assert (
        item["hostname"],
        item["mac_address"],
        item["operating_system"],
        item["connected_device"],
        item["connected_port"],
    ) == ("target.example", MAC, "Target OS", "DS-TARGET", "89")
    with sf() as db:
        stored = db.get(m.Job, job["id"])
        assert stored.status == "succeeded" and stored.progress == stored.total == 1
        assert service.enrich(db, [db.get(m.IPAddress, other_id)])[0] == before
        assert [(o.id, o.evidence) for o in db.scalars(select(m.Observation))] == shared
        assert db.get(m.VLAN, vlan_id).last_discovery_at is None
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1
        assert not db.scalar(select(m.IPObservation.id).where(m.IPObservation.source == NETWORK_SOURCE))


async def test_changed_address_is_cancelled_before_results_are_saved(admin_client, network, monkeypatch):
    sf, _, id, _ = network

    async def gateway(*_):
        with sf() as db:
            db.get(m.IPAddress, id).address = "192.0.2.90"
            db.commit()
        return [MAC]

    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(ipam_gateway=gateway))
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "cancelled"
        assert not db.scalar(select(m.IPAMResult.id))
