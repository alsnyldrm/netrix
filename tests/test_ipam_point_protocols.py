"""Protocol requests are exact IP/FID/MAC and never expand to ARP/FDB/inventory walks."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from netrix.discovery import point, protocols
from netrix.ipam import adapters

MAC = "00:11:22:33:44:55"


async def test_gateway_gets_only_selected_ip_and_interface(monkeypatch):
    calls = []

    class Query:
        async def get(self, oids):
            calls.extend(oids)
            return {
                oid: SimpleNamespace(asOctets=lambda: bytes.fromhex(MAC.replace(":", "")))
                if ".22.1.2." in oid
                else 3
                for oid in oids
            }

        async def metadata(self, *_):
            raise AssertionError("Known interface must not enumerate ARP")

    @asynccontextmanager
    async def reader(*_):
        yield Query()

    monkeypatch.setattr(point, "reader", reader)
    assert await point.gateway(
        "198.51.100.1", 161, {}, "192.0.2.10", {"indexes": [40], "network": "192.0.2.0/24"}
    ) == [MAC]
    assert len(calls) == 2 and all(o.endswith(".40.192.0.2.10") for o in calls)


@pytest.mark.parametrize("shared", [False, True])
async def test_switch_gets_only_selected_fid_mac_and_rejects_shared_fid(monkeypatch, shared):
    calls = []

    class Query:
        async def metadata(self, oid, **_):
            assert oid == protocols.IPAM_TABLES["vlan_fdb_id"]
            return {"0.20": "700", **({"0.30": "700"} if shared else {})}

        async def get(self, oids):
            calls.extend(oids)
            result = {}
            for oid in oids:
                if oid.startswith(protocols.IPAM_TABLES["vlan_fdb_port"] + "."):
                    result[oid] = 9
                elif oid.startswith(protocols.IPAM_TABLES["vlan_fdb_status"] + "."):
                    result[oid] = 3
                elif oid.startswith(protocols.IPAM_TABLES["bridge_ifindex"] + "."):
                    result[oid] = 101
                elif oid.startswith(protocols.IPAM_TABLES["if_name"] + "."):
                    result[oid] = "A7"
                elif oid.startswith(protocols.IPAM_TABLES["if_status"] + "."):
                    result[oid] = 1
            return result

    @asynccontextmanager
    async def reader(*_):
        yield Query()

    monkeypatch.setattr(point, "reader", reader)
    result = await point.switch("198.51.100.2", 161, {}, MAC, 20, {"tables": {}})
    assert result["ports"] == ([] if shared else [{"port": "A7", "if_index": 101}])
    if shared:
        assert not calls
    else:
        fdb = [o for o in calls if o.startswith(protocols.IPAM_TABLES["vlan_fdb_port"] + ".")]
        assert fdb == [protocols.IPAM_TABLES["vlan_fdb_port"] + ".700.0.17.34.51.68.85"]


def test_dhcp_point_uses_ip_client_filters_and_preserves_conflicts(monkeypatch):
    captured = {}

    def reader(config, secret, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(adapters, "windows_dhcp", reader)
    assert adapters.windows_dhcp_point(None, {}, "192.0.2.10", MAC) == []
    script = captured["script"]
    assert "-IPAddress '192.0.2.10'" in script and "-ClientId '00-11-22-33-44-55'" in script
    assert "-AllLeases" not in script and captured["point"] and captured["preserve_conflicts"]
    with pytest.raises(ValueError):
        adapters.windows_dhcp_point(None, {}, "';Remove-Item x", MAC)
    raw = b'[{"address":"192.0.2.10","mac_address":"00:11:22:33:44:55","reserved":true},{"address":"192.0.2.10","mac_address":"00:11:22:33:44:66","reserved":false}]'
    assert len(adapters.dhcp_records(raw, preserve_conflicts=True)) == 2


def test_vmware_point_searches_only_ip_and_its_nic(monkeypatch):
    from pyVim import connect
    from pyVmomi import vim

    card = vim.vm.device.VirtualVmxnet3(key=4000, macAddress=MAC)
    guest = SimpleNamespace(
        net=[SimpleNamespace(deviceConfigId=4000, macAddress=MAC, ipAddress=["192.0.2.10"])],
        hostName="VM-TARGET",
        guestFullName="Windows",
    )
    vm = SimpleNamespace(
        _moId="vm-1",
        guest=guest,
        name="VM-TARGET",
        config=SimpleNamespace(guestFullName="Windows", hardware=SimpleNamespace(device=[card])),
        runtime=SimpleNamespace(host=None, powerState="poweredOn"),
    )
    calls = []

    def search(**args):
        calls.append(args)
        return [vm] if args["vmSearch"] else []

    content = SimpleNamespace(searchIndex=SimpleNamespace(FindAllByIp=search))
    monkeypatch.setattr(
        adapters, "connect_vcenter", lambda *_: SimpleNamespace(RetrieveContent=lambda: content)
    )
    monkeypatch.setattr(connect, "Disconnect", lambda _: None)
    result = adapters.vcenter_point(None, {}, "192.0.2.10", MAC)
    assert calls == [{"ip": "192.0.2.10", "vmSearch": True}]
    assert len(result) == 1 and result[0]["hostname"] == "VM-TARGET" and result[0]["mac_address"] == MAC
