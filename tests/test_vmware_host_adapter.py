from types import SimpleNamespace as NS

from netrix.ipam import vmware_hosts


def test_host_adapter_reads_vmks_physical_macs_and_typed_network_hints():
    hints = vmware_hosts.hints(
        [
            NS(
                device="vmnic0",
                connectedSwitchPort=None,
                lldpInfo=NS(
                    timeToLive=120,
                    chassisId="00:11:22:33:44:55",
                    portId="263",
                    parameter=[
                        NS(key="Management Address", value="192.0.2.1"),
                        NS(key="Port Description", value="I7"),
                    ],
                ),
            ),
            NS(device="vmnic1", connectedSwitchPort=NS(portId="B2", address="192.0.2.2"), lldpInfo=None),
            NS(
                device="vmnic2",
                connectedSwitchPort=None,
                lldpInfo=NS(timeToLive=0, chassisId="old", portId="A1"),
            ),
        ]
    )
    values = {
        "name": "esxi.test",
        "hardware.systemInfo.uuid": "host-uuid",
        "config.network.vnic": [
            NS(
                device="vmk0",
                spec=NS(
                    mac="00:11:22:33:44:99",
                    ip=NS(
                        ipAddress="192.0.2.10",
                        ipV6Config=NS(ipV6Address=[NS(ipAddress="2001:db8::10"), NS(ipAddress="fe80::1")]),
                    ),
                ),
            )
        ],
        "config.network.pnic": [
            NS(device="vmnic0", mac="0011.2233.4466", linkSpeed=NS(speedMb=10000)),
            NS(device="vmnic1", mac="00:11:22:33:44:77", linkSpeed=None),
        ],
        "config.product.fullName": "VMware ESXi 8.0",
        "runtime.connectionState": "connected",
    }
    rows = vmware_hosts.records("host-1", values, hints)
    assert {r["address"] for r in rows} == {"192.0.2.10", "2001:db8::10"}
    assert rows[0]["physical_nics"][0]["mac_address"] == "00:11:22:33:44:66"
    assert rows[0]["physical_nics"][0]["hints"][0]["port_description"] == "I7"
    assert rows[0]["physical_nics"][1]["link_up"] is False
    assert hints["vmnic2"] == [] and hints["vmnic1"][0]["protocol"] == "cdp"
    values["runtime.connectionState"] = "disconnected"
    assert vmware_hosts.records("host-1", values, hints) == []


def test_vmkernel_uplinks_follow_own_standard_or_distributed_switch():
    values = {
        "config.network.pnic": [
            NS(key="key0", device="vmnic0"),
            NS(key="key1", device="vmnic1"),
            NS(key="key2", device="vmnic2"),
        ],
        "config.network.portgroup": [NS(spec=NS(name="Management", vswitchName="vSwitch0"))],
        "config.network.vswitch": [NS(name="vSwitch0", pnic=["key0"])],
        "config.network.proxySwitch": [NS(dvsUuid="dvs-1", pnic=["key1", "key2"])],
    }
    standard = NS(spec=NS(), portgroup="Management")
    distributed = NS(spec=NS(distributedVirtualPort=NS(switchUuid="dvs-1")))
    assert vmware_hosts.uplink_devices(standard, values) == {"vmnic0"}
    assert vmware_hosts.uplink_devices(distributed, values) == {"vmnic1", "vmnic2"}
    assert vmware_hosts.uplink_devices(NS(spec=NS(), portgroup="unknown"), values) == set()
    distributed.spec.pinnedPnicDevice = "vmnic2"
    assert vmware_hosts.uplink_devices(distributed, values) == {"vmnic2"}


def test_chassis_mac_and_port_mac_can_belong_to_different_host_cards():
    host = {
        "physical_nics": [
            {"device": "vmnic0", "mac_address": "00:11:22:33:44:01", "link_up": True},
            {"device": "vmnic1", "mac_address": "00:11:22:33:44:02", "link_up": True},
        ]
    }
    data = {
        "lldp": {
            "chassis_subtype": 4,
            "chassis_id": "00:11:22:33:44:01",
            "port_subtype": 3,
            "port_id": "00:11:22:33:44:02",
        }
    }
    assert vmware_hosts.nic_for_neighbor(host, data)["device"] == "vmnic1"
    data["lldp"]["port_id"] = "00:11:22:33:44:99"
    assert vmware_hosts.nic_for_neighbor(host, data) is None
