"""A VLAN scan owns completion of its source reads and final IP matching."""

import asyncio
from types import SimpleNamespace

from netrix import models as m
from netrix import worker
from netrix.ipam import adapters, jobs, service
from sqlalchemy import select
from test_ipam_workspace import integration, prefix


async def run_scan(env, monkeypatch, id, *, check=None):
    monkeypatch.setattr(worker, "stop", False)
    loop = asyncio.create_task(worker.worker_loop())
    try:
        async with asyncio.timeout(15):
            while True:
                with env() as db:
                    job = db.get(m.Job, id)
                    status = job.status
                    if check:
                        check(db, job)
                if status not in ("queued", "running"):
                    return status
                await asyncio.sleep(0.05)
    finally:
        monkeypatch.setattr(worker, "stop", True)
        await asyncio.wait_for(loop, 5)


async def test_new_vlan_waits_for_sources_and_matches_all_fields(admin_client, inventory, env, monkeypatch):
    vlan = prefix(admin_client, inventory)
    vc = integration(admin_client, vlan)
    dhcp = integration(admin_client, vlan, name="DHCP", kind="windows_dhcp", port=5986)
    with env() as db:
        gateway = m.Device(
            name="Gateway",
            management_ip="198.51.100.1",
            kind="firewall",
            vrf_id=vlan["vrf_id"],
            discovery_scope_id=inventory["scope"]["id"],
            snmp_credential_id=inventory["credential"]["id"],
        )
        switch = m.Device(
            name="Access",
            management_ip="198.51.100.2",
            kind="switch",
            vrf_id=vlan["vrf_id"],
            discovery_scope_id=inventory["scope"]["id"],
            snmp_credential_id=inventory["credential"]["id"],
        )
        db.add_all([gateway, switch])
        db.commit()
    initial = admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").json()
    assert initial["kind"] == "ipam_discover" and initial["status"] == "queued"
    assert admin_client.post(f"/api/v1/ipam/vlans/{vlan['id']}/discover").json()["id"] == initial["id"]
    phases = set()
    calls = []

    async def ping(address):
        return address.endswith(".2")

    async def dns(address, server):
        calls.append(("dns", address))
        return "dns-" + address

    def dhcp_read(*_):
        calls.append(("dhcp", "read"))
        return [{"address": "192.0.2.1", "hostname": "not-dns", "mac_address": "00:11:22:33:44:66"}]

    def vm_read(*_):
        with env() as db:
            assert db.scalar(select(m.IPObservation).where(m.IPObservation.source == "windows_dhcp"))
            assert db.get(m.Job, initial["id"]).status == "running"
        calls.append(("vmware", "read"))
        return [
            {
                "address": "192.0.2.2",
                "mac_address": "00:11:22:33:44:55",
                "vm_id": "vm-1",
                "nic_key": "4000",
                "operating_system": "Ubuntu",
                "dvswitch_name": "DS",
                "dvport": "89",
            }
        ]

    async def network(host, *_):
        tables = (
            {
                "arp_mac": {"40.192.0.2.1": "00:11:22:33:44:66", "40.192.0.2.2": "00:11:22:33:44:55"},
                "ip_addr_ifindex": {"192.0.2.1": "40"},
                "ip_addr_mask": {"192.0.2.1": "255.255.255.252"},
            }
            if host.endswith(".1")
            else {
                "vlan_fdb_id": {f"0.{vlan['vid']}": "700"},
                "vlan_fdb_port": {"700.0.17.34.51.68.102": "1"},
                "vlan_fdb_status": {"700.0.17.34.51.68.102": "3"},
                "bridge_ifindex": {"1": "101"},
            }
        )
        return {
            "tables": tables,
            "interfaces": [{"if_index": 101, "name": "A1", "oper_status": "up"}],
            "neighbors": [],
            "neighbor_protocols_complete": ["lldp"],
        }

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr(adapters, "windows_dhcp", dhcp_read)
    monkeypatch.setattr(adapters, "vcenter_records", vm_read)
    monkeypatch.setattr(worker, "SNMPCollector", lambda: SimpleNamespace(ipam=network))
    assert (
        await run_scan(
            env, monkeypatch, initial["id"], check=lambda db, j: phases.add(j.result.get("scan_phase"))
        )
        == "succeeded"
    )
    result = admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").json()
    assert result["result"]["scan_phase"] == "complete"
    assert set(result["result"]["source_statuses"].values()) == {"succeeded"}
    assert result["result"]["matching"] == {
        "addresses": 2,
        "hostname": 2,
        "mac_address": 2,
        "connected_device": 2,
        "connected_port": 2,
        "operating_system": 1,
        "ambiguous": 0,
    }
    assert calls.index(("dhcp", "read")) < calls.index(("vmware", "read"))
    assert ("dns", "192.0.2.1") in calls
    with env() as db:
        rows = {r["address"]: r for r in service.enrich(db, list(db.scalars(select(m.IPAddress))))}
        assert rows["192.0.2.1"]["hostname"] == "dns-192.0.2.1"
        assert (
            rows["192.0.2.1"]["connected_device"] == "Access" and rows["192.0.2.1"]["connected_port"] == "A1"
        )
        assert rows["192.0.2.2"]["mac_address"] == "00:11:22:33:44:55"
        assert (
            rows["192.0.2.2"]["operating_system"] == "Ubuntu" and rows["192.0.2.2"]["connected_port"] == "89"
        )
        sources = list(db.scalars(select(m.Job).where(m.Job.kind == "integration")))
        assert len(sources) == 2 and {s.target_id for s in sources} == {vc["id"], dhcp["id"]}


async def test_source_wait_reports_failure_timeout_missing_and_cancellation(
    admin_client, inventory, env, monkeypatch
):
    import pytest
    from netrix.worker import Cancelled

    vlan = prefix(admin_client, inventory)
    parent = admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").json()
    with env() as db:
        failed = m.Job(kind="integration", target_id="source", status="failed")
        pending = m.Job(kind="integration", target_id="other", status="queued")
        db.add_all([failed, pending])
        db.commit()
        f, p = failed.id, pending.id
    assert await jobs.wait_for_sources(parent["id"], [f, "missing"]) == {f: "failed", "missing": "missing"}
    monkeypatch.setattr(jobs, "SOURCE_WAIT_SECONDS", 0)
    assert await jobs.wait_for_sources(parent["id"], [p]) == {p: "timeout"}
    with env() as db:
        db.get(m.Job, parent["id"]).cancel_requested = True
        db.commit()
    with pytest.raises(Cancelled):
        await jobs.wait_for_sources(parent["id"], [p])
