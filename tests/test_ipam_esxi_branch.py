"""ESXi hosts continue through physical sources; only VMs short-circuit the branch."""

import pytest
from netrix import models as m
from netrix import worker
from netrix.ipam import adapters, pipeline
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network


@pytest.mark.parametrize("record_type", ["host", "vm"])
async def test_manual_ip_classifies_vm_and_host_before_selecting_sources(
    admin_client, network, monkeypatch, record_type
):
    sf, vlan_id, id, _ = network
    calls = []

    class Sources:
        async def gateway(self, address):
            calls.append("gateway")
            return {"mac_address": MAC, "gateway_evidence": []}

        async def vmware(self, address, mac):
            calls.append("vmware")
            return [
                {
                    "address": address,
                    "mac_address": mac,
                    "record_type": record_type,
                    "host_id": "host-1" if record_type == "host" else None,
                    "vm_id": "vm-1" if record_type == "vm" else None,
                    "nic_key": "1",
                    "hostname": "vmware-name",
                    "operating_system": "VMware ESXi" if record_type == "host" else "Linux",
                    # A host's own virtual backing and VMware hints are not its physical connection.
                    "vswitch_name": "vSwitch0" if record_type == "host" else "FBU-DS",
                    "port": "vmk0" if record_type == "host" else "89",
                    "physical_nics": [
                        {
                            "link_up": True,
                            "carries_ip": True,
                            "hints": [{"chassis_id": "VMWARE-HINT", "port_id": "wrong-port"}],
                        }
                    ],
                }
            ]

        async def physical(self, address, mac):
            assert record_type == "host" and mac == MAC
            calls.append("physical")
            return {
                "connections": [
                    {"device_id": device, "device_name": device, "port": port, "aggregate": "Trk1"}
                    for device, port in (("BB1", "H7"), ("BB1", "H8"), ("BB2", "B7"))
                ]
            }

        async def dhcp(self, address, mac):
            assert record_type == "host" and mac == MAC
            calls.append("dhcp")
            return [{"address": address, "mac_address": mac, "hostname": "dhcp-name"}]

        async def dns(self, address):
            assert record_type == "host"
            calls.append("dns")
            return "esxi.example.test"

    monkeypatch.setattr(pipeline, "sources_for", lambda *_: Sources())

    async def ping(address):
        return True

    monkeypatch.setattr(adapters, "ping", ping)
    job = admin_client.post(f"/api/v1/ipam/addresses/{id}/scan").json()
    await worker.execute(job["id"], object())
    detail = admin_client.get(f"/api/v1/ipam/addresses/{id}").json()
    assert detail["scan_status"] == "success"
    if record_type == "host":
        assert calls == ["gateway", "vmware", "physical", "dhcp", "dns"]
        assert detail["connected_device"] == "BB1 / BB2"
        assert detail["connected_port"] == "H7 Trk1 - H8 Trk1 / B7 Trk1"
        assert detail["hostname"] == "esxi.example.test" and not detail["operating_system"]
        assert detail["connection_type"] == "physical" and detail["cabinet"] != "Sanal"
        assert not any(s["status"] == "skipped_vm" for s in detail["scan_result"]["steps"])
    else:
        assert calls == ["gateway", "vmware"]
        assert detail["connected_device"] == "FBU-DS" and detail["connected_port"] == "89"
        assert detail["hostname"] == "vmware-name" and detail["operating_system"] == "Linux"
        assert detail["connection_type"] == "vcenter" and detail["cabinet"] == "Sanal"
    with sf() as db:
        assert db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == id))
