"""Only explicit scans collect sources; each completed IP is durably published alone."""

import asyncio
from types import SimpleNamespace

import pytest
from conftest import vlan_payload
from netrix import models as m
from netrix import services, worker
from netrix.ipam import adapters, service
from sqlalchemy import select
from test_ipam_workspace import integration, prefix


def test_new_vlan_and_repeated_reads_never_enqueue_scan(admin_client, inventory, env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata and GET requests cannot enqueue or collect")

    monkeypatch.setattr(services, "enqueue", forbidden)
    payload = vlan_payload({"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]})
    response = admin_client.post("/api/v1/vlans", json=payload)
    assert response.status_code == 201, response.text
    vlan = response.json()
    assert "scan" not in vlan
    row = admin_client.post(
        "/api/v1/addresses",
        json={"address": "192.0.2.1", "vlan_id": vlan["id"], "vrf_id": vlan["vrf_id"]},
    ).json()
    for _ in range(3):
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/addresses/{row['id']}").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").json() is None
    with env() as db:
        assert not db.scalar(select(m.Job))


@pytest.mark.parametrize("slow_first", [False, True])
async def test_manual_vlan_targets_only_its_ips_and_publishes_before_other_ip_finishes(
    admin_client, inventory, env, monkeypatch, slow_first
):
    vlan = prefix(admin_client, inventory)
    other = prefix(admin_client, inventory, "198.51.100.0/30")
    integration(admin_client, vlan)
    integration(admin_client, vlan, name="DHCP", kind="windows_dhcp", port=5986)
    with env() as db:
        db.add(
            m.Device(
                name="Gateway",
                kind="firewall",
                management_ip="192.0.2.254",
                vrf_id=vlan["vrf_id"],
                discovery_scope_id=inventory["scope"]["id"],
                snmp_credential_id=inventory["credential"]["id"],
            )
        )
        v = db.get(m.VLAN, other["id"])
        outside = service.observe(db, v, "198.51.100.1", "dns", "system", {"hostname": "unchanged"})
        db.commit()
        outside_id = outside.id
    release, waiting = asyncio.Event(), asyncio.Event()
    slow = "192.0.2.1" if slow_first else "192.0.2.2"
    fast = "192.0.2.2" if slow_first else "192.0.2.1"
    calls, committed = [], asyncio.Event()

    def forbidden(*args, **kwargs):
        raise AssertionError("Manual VLAN must not read full ARP/FDB/VMware/DHCP tables")

    async def gateway(host, port, secret, address, hint):
        assert hint["network"] == vlan["cidr"]
        assert address in (slow, fast)
        calls.append(("gateway", address))
        return ["00:11:22:33:44:" + ("55" if address == fast else "66")]

    async def ping(address):
        assert address in (slow, fast)
        return address == fast  # The other endpoint is discovered through gateway only.

    def vmware(config, secret, address, mac, hints):
        calls.append(("vmware", address))
        assert ("gateway", address) in calls
        return [
            {
                "address": address,
                "mac_address": mac,
                "vm_id": address,
                "nic_key": "1",
                "hostname": "vm-" + address,
                "operating_system": "Linux",
                "dvswitch_name": "DS",
                "dvport": "89",
            }
        ]

    from netrix.ipam.point_sources import PointSources

    original = PointSources.vmware

    async def wait_vmware(self, address, mac):
        if address == slow:
            waiting.set()
            await release.wait()
        return await original(self, address, mac)

    def published(*args, **kwargs):
        if kwargs.get("ipam_vlan") != vlan["id"]:
            return
        with env() as db:
            result = db.scalar(select(m.IPAMResult).join(m.IPAddress).where(m.IPAddress.address == fast))
            if result and result.values.get("hostname") == "vm-" + fast:
                committed.set()

    monkeypatch.setattr(PointSources, "vmware", wait_vmware)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "vcenter_point", vmware)
    for name in ("vcenter_records", "windows_dhcp", "windows_dhcp_point", "reverse_dns"):
        monkeypatch.setattr(adapters, name, forbidden)
    monkeypatch.setattr("netrix.ipam.vlan_pipeline.publish", published)
    collector = SimpleNamespace(ipam=forbidden, ipam_gateway=gateway, ipam_switch=forbidden)
    job = admin_client.post(f"/api/v1/ipam/vlans/{vlan['id']}/discover").json()
    assert job["result"]["ipam_origin"] == "manual"
    task = asyncio.create_task(worker.execute(job["id"], collector))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        await asyncio.wait_for(committed.wait(), 5)
        assert not task.done()
        visible = admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses?registered_only=true").json()
        assert any(r.get("hostname") == "vm-" + fast for r in visible["items"])
    finally:
        release.set()
        await asyncio.wait_for(task, 10)
    with env() as db:
        assert db.get(m.Job, job["id"]).status == "succeeded"
        assert not db.scalar(select(m.IPAMNetworkState))
        assert not db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == outside_id))
        assert db.get(m.IPAddress, outside_id).hostname == ""
        assert len(list(db.scalars(select(m.IPAMResult)))) == 2
    assert sorted(calls) == sorted((kind, ip) for ip in (slow, fast) for kind in ("gateway", "vmware"))
