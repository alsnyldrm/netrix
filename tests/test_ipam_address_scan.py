"""One explicit IP probe; scoped source writes never alter another address or shared snapshots."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import services, worker
from netrix.discovery.protocols import NetworkError
from netrix.ipam import adapters, service
from netrix.ipam.address_scan import NETWORK_SOURCE
from sqlalchemy import func, select
from test_ipam_source_contract import network as network
from test_ipam_workspace import integration
from test_switch_mac_cache import cache

MAC = "00:11:22:33:44:66"


@pytest.mark.parametrize("ip", ["198.51.100.10", "192.0.2.0", "192.0.2.255"])
def test_rejects_outside_network_and_non_host_targets(admin_client, network, ip):
    sf, _, id, _ = network
    with sf() as db:
        db.get(m.IPAddress, id).address = ip
        db.commit()
    assert admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").status_code == 422


async def test_new_empty_ip_scan_does_not_resurrect_older_cached_mac_port(admin_client, network, monkeypatch):
    sf, _, id, _ = network
    cache(network, port="Gi1/0/1")
    with sf() as db:
        payloads = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}
    for host in ("198.51.100.2", "198.51.100.3"):
        payloads[host]["tables"]["vlan_fdb_port"] = {}
        payloads[host]["tables"]["vlan_fdb_status"] = {}

    async def ping(_):
        return True

    async def dns(*_):
        return "target.example"

    async def ipam(host, *_):
        return payloads[host]

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(ipam=ipam))
    assert not address(network)["connected_device"]


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
    sf, vlan_id, id, ids = network
    config = integration(admin_client, {"id": vlan_id})
    integration(admin_client, {"id": vlan_id}, name="DHCP", kind="windows_dhcp", port=5986)
    with sf() as db:
        vlan = db.get(m.VLAN, vlan_id)
        other = service.observe(db, vlan, "192.0.2.11", "dns", "system", {"hostname": "unchanged.example"})
        service.observe(db, vlan, other.address, "icmp", vlan.id, {"reachability": "no_reply"})
        service.observe(
            db,
            vlan,
            other.address,
            "windows_dhcp",
            "foreign-source",
            {"hostname": "old-dhcp", "mac_address": MAC, "reserved": True},
        )
        db.commit()
        other_id = other.id
        before = service.enrich(db, [other])[0]
        raw = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}
        shared = [(o.id, o.created_at, deepcopy(o.evidence)) for o in db.scalars(select(m.Observation))]
        count = db.scalar(select(func.count()).select_from(m.IPAddress))
    raw["198.51.100.1"]["tables"]["arp_mac"]["40.192.0.2.10"] = MAC
    for host in ("198.51.100.2", "198.51.100.3"):
        tables = raw[host]["tables"]
        fid = "700" if host.endswith(".2") else "900"
        port = "9" if host.endswith(".2") else "3"
        tables["vlan_fdb_port"] = {fid + ".0.17.34.51.68.102": port}
        tables["vlan_fdb_status"] = {fid + ".0.17.34.51.68.102": "3"}
    pinged, resolved = [], []

    async def ping(ip):
        pinged.append(ip)
        return True

    async def dns(ip, server):
        resolved.append(ip)
        return "target.example"

    async def ipam(host, *_):
        return raw[host]

    def vm_records(*_):
        record = {
            "address": "192.0.2.10",
            "hostname": "target.example",
            "mac_address": MAC,
            "vm_id": "vm-target",
            "nic_key": "4000",
            "operating_system": "Target OS",
            "power_state": "poweredOn",
            "dvswitch_name": "DS-TARGET",
            "dvport": "89",
            "network": "VLAN-020",
        }
        return [
            record,
            {**record, "address": "2001:db8::10"},
            {
                **record,
                "address": "192.0.2.11",
                "vm_id": "vm-other",
                "mac_address": "00:11:22:33:44:88",
                "hostname": "must-not-import",
            },
        ]

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr(adapters, "vcenter_records", vm_records)
    monkeypatch.setattr(
        adapters,
        "windows_dhcp",
        lambda *_: [
            {"address": "192.0.2.10", "hostname": "target-dhcp", "mac_address": MAC, "reserved": True},
            {"address": "192.0.2.50", "hostname": "must-not-create", "mac_address": MAC},
        ],
    )
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert not pinged and not resolved
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(ipam=ipam))
    assert pinged == resolved == ["192.0.2.10"]
    item = address(network)
    assert item["hostname"] == "target.example" and item["mac_address"] == MAC
    assert item["operating_system"] == "Target OS"
    assert item["connected_device"] == "DS-TARGET" and item["connected_port"] == "89"
    assert all(o["source"] != NETWORK_SOURCE for o in item["observations"])
    with sf() as db:
        stored = db.get(m.Job, job["id"])
        assert stored.status == "succeeded" and stored.progress == stored.total == 1
        assert stored.result["checked"] == 1
        assert db.scalar(select(func.count()).select_from(m.Job)) == 2
        assert db.scalar(select(func.count()).select_from(m.IPAddress)) == count
        assert service.enrich(db, [db.get(m.IPAddress, other_id)])[0] == before
        assert [
            (o.id, o.created_at, o.evidence)
            for o in db.scalars(select(m.Observation).where(m.Observation.source == "ipam_network"))
        ] == shared
        assert db.get(m.VLAN, vlan_id).last_discovery_at is None
        scoped = list(db.scalars(select(m.IPObservation).where(m.IPObservation.source == NETWORK_SOURCE)))
        assert len(scoped) == 3 and {o.address_id for o in scoped} == {id}
        assert all("evidence" not in o.data and o.data["observation_id"] for o in scoped)
        nic = db.scalar(
            select(m.IPObservation).where(
                m.IPObservation.address_id == id, m.IPObservation.source == "vcenter"
            )
        )
        assert nic.data["guest_address"] == "192.0.2.10" and not nic.data.get("matched_by")
        assert db.get(m.Integration, config["id"]).last_run_at is None


async def test_failed_source_is_partial_and_does_not_refresh_shared_evidence(
    admin_client, network, monkeypatch
):
    sf, _, id, _ = network
    with sf() as db:
        raw = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}

    async def ping(_):
        return False

    async def dns(*_):
        return "offline.example"

    async def ipam(host, *_):
        if host == "198.51.100.2":
            raise NetworkError("fixture failure")
        return raw[host]

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(ipam=ipam))
    with sf() as db:
        result = db.get(m.Job, job["id"])
        assert result.status == "partial" and result.result["network"]["failed"] == 1
    item = address(network)
    assert item["hostname"] == "offline.example" and item["availability"] == "passive"
    assert not item["connected_device"]


async def test_changed_address_is_cancelled_before_network_results_are_saved(
    admin_client, network, monkeypatch
):
    sf, _, id, _ = network

    async def ping(_):
        return True

    async def dns(*_):
        return "old-address.example"

    async def ipam(*_):
        with sf() as db:
            db.get(m.IPAddress, id).address = "192.0.2.90"
            db.commit()
        return {"interfaces": [], "tables": {}, "neighbors": []}

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(ipam=ipam))
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "cancelled"
        assert not db.scalar(select(m.IPObservation.id).where(m.IPObservation.source == NETWORK_SOURCE))
