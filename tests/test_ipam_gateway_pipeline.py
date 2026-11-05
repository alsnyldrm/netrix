"""Gateway-first branching, stable bounded results, and target-only protocol reads."""

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.ipam import adapters
from sqlalchemy import func, select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network


async def test_vm_branch_never_reads_dns_dhcp_or_switches(admin_client, network, monkeypatch):
    from netrix.ipam import pipeline

    calls = []

    class Sources:
        async def gateway(self, address):
            calls.append(("gateway", address))
            return {"mac_address": MAC, "gateway_evidence": []}

        async def vmware(self, address, mac):
            calls.append(("vmware", address, mac))
            return [
                {
                    "address": address,
                    "mac_address": MAC,
                    "vm_id": "vm1",
                    "nic_key": "1",
                    "hostname": "VM-NAME",
                    "operating_system": "Windows",
                    "dvswitch_name": "FBU-DS",
                    "dvport": "89",
                    "network": "VLAN-020",
                }
            ]

        async def physical(self, *_):
            raise AssertionError("VM branch cannot query switches")

        async def dhcp(self, *_):
            raise AssertionError("VM branch cannot query DHCP")

        async def dns(self, *_):
            raise AssertionError("VM branch cannot query DNS")

    async def ping(_):
        return True

    monkeypatch.setattr(adapters, "ping", ping)
    sf, _, id, _ = network
    result = await pipeline.resolve("192.0.2.10", Sources())
    with sf() as db:
        pipeline.save_result(db, db.get(m.IPAddress, id), now(), result)
        db.commit()
    assert [c[0] for c in calls] == ["gateway", "vmware"]
    row = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert (row["hostname"], row["mac_address"], row["connected_device"], row["connected_port"]) == (
        "VM-NAME",
        MAC,
        "FBU-DS",
        "89",
    )
    assert row["scan_result"]["status"] == "success"
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1


async def test_physical_branch_dhcp_conflict_and_multiport(network):
    from netrix.ipam.pipeline import resolve

    calls = []

    class Sources:
        async def gateway(self, a):
            calls.append("gateway")
            return {"mac_address": MAC, "gateway_evidence": []}

        async def vmware(self, *_):
            calls.append("vmware")
            return []

        async def physical(self, *_):
            calls.append("physical")
            return {
                "connections": [
                    {
                        "device_id": "d1",
                        "device_name": "BB1",
                        "port": p,
                        "aggregate": "Trk1",
                        "endpoint_identity": "server1",
                    }
                    for p in ("H7", "H8")
                ]
            }

        async def dhcp(self, a, mac):
            calls.append("dhcp")
            return [{"address": a, "mac_address": "00:11:22:33:44:66", "hostname": "WRONG", "reserved": True}]

        async def dns(self, a):
            calls.append("dns")
            return "server.example"

    result = await resolve("192.0.2.10", Sources())
    assert calls == ["gateway", "vmware", "physical", "dhcp", "dns"]
    assert result["values"]["hostname"] == "YANLIŞ-DHCP-VERİSİ"
    assert result["values"]["mac_address"] == MAC
    assert result["values"]["connected_port"] == "H7 Trk1 - H8 Trk1"
    assert result["status"] == "problem" and "DHCP" in str(result["issues"])
    assert result["values"]["operating_system"] == ""


async def test_partial_failure_preserves_last_good_fields_and_row_count(admin_client, network, monkeypatch):
    from netrix.ipam import pipeline

    sf, _, id, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, id)
        from netrix.ipam import service

        vlan = db.get(m.VLAN, row.vlan_id)
        service.observe(db, vlan, row.address, "dns", "system", {"hostname": "stable"})
        source = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == network[3][1]))
        for port in source.ports:
            if port.if_index == 101:
                port.name = "7"
        for entry in source.mac_entries:
            entry.port = "7"
        db.flush()
        pipeline.save_result(
            db,
            row,
            now(),
            {
                "status": "success",
                "values": {
                    "hostname": "stable",
                    "mac_address": MAC,
                    "connected_device": "Access",
                    "connected_port": "7",
                    "connection_type": "physical",
                },
                "issues": [],
                "steps": [],
            },
        )
        db.commit()

    class Sources:
        async def gateway(self, *_):
            raise TimeoutError()

        async def vmware(self, *_):
            return []

        async def physical(self, *_):
            raise AssertionError("No MAC means no switch query")

        async def dhcp(self, *_):
            raise AssertionError("No MAC means no DHCP query")

        async def dns(self, *_):
            return ""

    for _ in range(3):
        result = await pipeline.resolve("192.0.2.10", Sources())
        with sf() as db:
            pipeline.save_result(db, db.get(m.IPAddress, id), now(), result)
            db.commit()
    row = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert row["hostname"] == "stable" and row["connected_port"] == "7"
    assert row["scan_result"]["status"] == "problem" and row["scan_result"]["retained"]
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1


@pytest.mark.parametrize("action", ["address", "vlan"])
async def test_manual_jobs_use_sql_gateway_and_mac_path(admin_client, network, monkeypatch, action):
    sf, _, id, _ = network
    calls = []

    class Collector:
        async def ipam(self, *_):
            raise AssertionError("Point scan must never read a whole table")

        async def ipam_gateway(self, host, port, secret, address, indexes):
            calls.append(("gateway", host, address))
            assert indexes["indexes"] == [40]
            return [MAC]

        async def ipam_switch(self, host, port, secret, mac, vid, hint):
            calls.append(("switch", host, mac))
            assert mac == MAC and vid == 20
            return {"ports": [{"port": "Gi1/0/1", "if_index": 101}], "neighbors": []}

    async def ping(_):
        return True

    async def dns(*_):
        return "target.example"

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    if action == "vlan":
        # Restrict the fixture to its known endpoint; CIDR expansion has its own tests.
        monkeypatch.setattr("netrix.ipam.vlan_pipeline.targets", lambda *_: ["192.0.2.10"])
        with sf() as db:
            vlan_id = db.get(m.IPAddress, id).vlan_id
        job = admin_client.post(f"/api/v1/ipam/vlans/{vlan_id}/discover").json()
    else:
        job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    assert worker.claim(interactive=False, include_kinds=(job["kind"],)) == job["id"]
    await worker.execute(job["id"], Collector())
    assert calls == []
    item = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert item["connected_device"] == "Access" and item["connected_port"] == "Gi1/0/1"
    assert item["scan_status"] == "success"


def test_older_attempt_cannot_overwrite_newer_and_manual_fields_keep_priority(admin_client, network):
    from datetime import timedelta

    from netrix.ipam.pipeline import save_result

    sf, _, id, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, id)
        row.hostname = "MANUAL"
        db.get(m.Device, network[3][1]).name = "new-switch"
        db.flush()
        current = now()
        save_result(
            db,
            row,
            current,
            {
                "status": "success",
                "values": {"hostname": "new", "mac_address": MAC, "connected_device": "new-switch"},
                "issues": [],
                "steps": [],
            },
        )
        db.commit()
        assert not save_result(
            db,
            row,
            current - timedelta(seconds=1),
            {"status": "success", "values": {"hostname": "old"}, "issues": [], "steps": []},
        )
        db.commit()
    item = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert item["hostname"] == "MANUAL" and item["connected_device"] == "new-switch"


async def test_conflicting_vm_does_not_fall_through_to_physical(network):
    from netrix.ipam.pipeline import resolve

    class Sources:
        async def gateway(self, a):
            return {"mac_address": MAC}

        async def vmware(self, a, mac):
            return [{"address": a, "mac_address": "00:11:22:33:44:66", "vm_id": "vm1"}]

        async def physical(self, *_):
            raise AssertionError("Conflicting VM must not be a physical endpoint")

        async def dns(self, *_):
            raise AssertionError("VM must skip DNS")

        async def dhcp(self, *_):
            raise AssertionError("VM must skip DHCP")

    result = await resolve("192.0.2.10", Sources())
    assert result["status"] == "problem" and result["values"]["mac_address"] == MAC
    assert any(i["source"] == "vmware" and i["code"] == "identity_conflict" for i in result["issues"])


async def test_offline_backfill_is_idempotent_and_never_probes(admin_client, network, monkeypatch):
    from netrix.ipam.backfill import run

    sf, _, id, _ = network

    def forbidden(*_):
        raise AssertionError("Offline backfill cannot contact any source")

    for name in (
        "ping",
        "reverse_dns",
        "vcenter_point",
        "windows_dhcp_point",
        "vcenter_records",
        "windows_dhcp",
    ):
        monkeypatch.setattr(adapters, name, forbidden)
    assert await run() == 1
    first = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert first["mac_address"] == MAC and first["connected_device"] == "Access"
    assert first["cached_import"] and all(s["mode"] == "stored" for s in first["scan_result"]["steps"])
    assert await run() == 0
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1


async def test_live_point_groups_two_nics_with_current_port_detail(admin_client, network, monkeypatch):
    import json

    from netrix.identity.security import encrypt
    from netrix.ipam import point_sources

    sf, vlan_id, id, ids = network
    neighbors = []
    for port, nic in (("H7", MAC), ("H8", "00:11:22:33:44:66")):
        neighbors.append(
            {
                "interface_name": port,
                "remote_name": "server",
                "remote_port": nic,
                "source": "lldp+cdp",
                "evidence": {
                    "local_aggregate": {"name": "Trk1"},
                    "lldp": {
                        "transport": "ssh_detail",
                        "chassis_subtype": 4,
                        "chassis_id": MAC,
                        "port_subtype": 3,
                        "port_id": nic,
                    },
                    "cdp": {
                        "transport": "ssh_detail",
                        "device_id": MAC,
                        "management_address": "192.0.2.10",
                        "port_id": nic,
                    },
                },
            }
        )
    with sf() as db:
        profile = m.Credential(
            name="SSH fixture",
            protocol="ssh",
            encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
        )
        db.add(profile)
        db.flush()
        device = db.get(m.Device, ids[1])
        device.adapter = "aruba_5400"
        device.config_credential_id = profile.id
        old = db.scalar(select(m.Observation).where(m.Observation.device_id == device.id))
        old.evidence = {
            **old.evidence,
            "interfaces": [
                {"if_index": i, "name": p, "oper_status": "up"}
                for i, p in ((101, "H7"), (102, "H8"), (103, "Trk1"))
            ],
            "neighbors": neighbors,
        }
        db.commit()

    async def detail(device, secret, ports):
        assert ports == ["H7", "H8"]
        return {"neighbors": neighbors, "trunks": {p: {"name": "Trk1"} for p in ("H7", "H8")}}

    class Collector:
        async def ipam_gateway(self, *_):
            return [MAC]

        async def ipam_switch(self, *_):
            return {"ports": [{"port": "Trk1", "if_index": 103}], "neighbors": []}

    async def ping(_):
        return True

    async def dns(*_):
        return "server.example"

    monkeypatch.setattr(point_sources, "fetch_neighbor_ports", detail)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    from netrix.ipam import pipeline

    with sf() as db:
        sources = point_sources.PointSources(
            db, db.get(m.IPAddress, id), db.get(m.VLAN, vlan_id), Collector()
        )
    result = await pipeline.resolve("192.0.2.10", sources)
    with sf() as db:
        pipeline.save_result(db, db.get(m.IPAddress, id), now(), result)
        db.commit()
    item = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert item["scan_status"] == "success", item["scan_result"]
    assert item["connected_port"] == "H7 Trk1 - H8 Trk1"


async def test_offline_transition_keeps_expired_last_known_mac_and_port(admin_client, network):
    from datetime import timedelta

    from netrix.ipam.backfill import run

    sf, _, id, _ = network
    with sf() as db:
        for observation in db.scalars(select(m.Observation)):
            observation.created_at = now() - timedelta(days=2)
            state = observation.network_state
            state.observed_at = state.gateway_at = state.fdb_at = observation.created_at
            for g in db.scalars(
                select(m.GatewayBinding).where(m.GatewayBinding.device_id == state.device_id)
            ):
                g.observed_at = observation.created_at
        db.commit()
    assert await run() == 1
    item = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert item["mac_address"] == MAC and item["connected_device"] == "Access"
    assert item["scan_result"]["retained"] and item["scan_status"] == "problem"
    assert any(i["code"] == "stale_source" for i in item["scan_result"]["issues"])
