from types import SimpleNamespace

import pytest
from conftest import make_vlan
from netrix import models as m
from netrix.core import now
from netrix.ipam import adapters, jobs, service


def endpoint(db, vrf_id):
    prefix = make_vlan(cidr="192.0.2.0/24", vrf_id=vrf_id)
    db.add(prefix)
    db.flush()
    row = service.observe(
        db, prefix, "192.0.2.11", "windows_dhcp", "dhcp", {"mac_address": "00:50:56:a0:42:c0"}
    )
    return prefix, row


def test_vm_connection_wins_over_physical_fdb_and_manual_port(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        config = m.Integration(
            name="vCenter",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            encrypted_secret="fixture",
        )
        db.add(config)
        db.flush()
        service.observe(
            db,
            prefix,
            row.address,
            "vcenter",
            config.id + ":vm-1:4000",
            {
                "vm_id": "vm-1",
                "nic_key": "4000",
                "integration_id": config.id,
                "mac_address": "00:50:56:a0:42:c0",
                "dvswitch": "uuid-1",
                "dvswitch_name": "FBU-DS",
                "network": "VLAN-020",
                "dvport": "89",
            },
        )
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "FBU-DS"
        assert result["connected_port"] == "89" and result["network"] == "VLAN-020"
        assert result["connection_type"] == "vcenter" and not result["connection_ambiguous"]
        options = jobs.connection_options(db, row)
        assert options["interfaces"] == []
        assert options["integrations"][0]["switch_name"] == "FBU-DS"


def test_vm_record_uses_backing_switch_and_portgroup_even_without_guest_network():
    from pyVmomi import vim

    card = vim.vm.device.VirtualVmxnet3(
        key=4000,
        macAddress="00:50:56:a0:42:c0",
        backing=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
            port=vim.dvs.PortConnection(switchUuid="uuid-1", portgroupKey="pg-1", portKey="89")
        ),
    )
    values = {
        "config.hardware.device": [card],
        "guest": SimpleNamespace(
            net=[SimpleNamespace(deviceConfigId=4000, ipAddress=["192.0.2.11"], network="wrong-old-name")]
        ),
    }
    rows = adapters.vm_records(
        "vm-1",
        values,
        {"switches": {"uuid-1": "FBU-DS"}, "portgroups": {("uuid-1", "pg-1"): "VLAN-020"}, "hosts": {}},
    )
    assert rows[0]["dvswitch_name"] == "FBU-DS" and rows[0]["network"] == "VLAN-020"
    assert rows[0]["portgroup_key"] == "pg-1" and rows[0]["dvport"] == "89"


async def test_dhcp_mac_matches_vm_without_guest_ip_and_removed_nic_is_retired(
    admin_client, inventory, env, monkeypatch
):
    import json

    from netrix.identity.security import encrypt

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        config = m.Integration(
            name="VC",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id)
        db.add(job)
        db.commit()
        job_id, row_id = job.id, row.id
    record = {
        "address": "",
        "mac_address": "00:50:56:a0:42:c0",
        "vm_id": "vm-1",
        "nic_key": "4000",
        "dvswitch_name": "FBU-DS",
        "dvport": "89",
        "network": "VLAN-020",
    }
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: [record])
    await jobs.integration(job_id)
    with env() as db:
        row = db.get(m.IPAddress, row_id)
        assert service.enrich(db, [row])[0]["connected_device"] == "FBU-DS"

    def failed_read(*_):
        raise adapters.NetworkError("incomplete snapshot")

    monkeypatch.setattr(adapters, "vcenter_records", failed_read)
    with pytest.raises(adapters.NetworkError):
        await jobs.integration(job_id)
    with env() as db:
        row = db.get(m.IPAddress, row_id)
        assert service.enrich(db, [row])[0]["connected_device"] == "FBU-DS"
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: [])
    await jobs.integration(job_id)
    with env() as db:
        row = db.get(m.IPAddress, row_id)
        assert service.enrich(db, [row])[0]["connection_type"] != "vcenter"
        assert jobs.connection_options(db, row)["integrations"] == []


def test_conflicting_vm_attachments_never_fall_back_to_a_physical_hop(admin_client, inventory, env):
    from datetime import timedelta

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        for number in (1, 2):
            service.observe(
                db,
                prefix,
                row.address,
                "vcenter",
                f"vc:vm-{number}",
                {
                    "vm_id": f"vm-{number}",
                    "nic_key": "4000",
                    "dvswitch_name": f"DS-{number}",
                    "dvport": str(number),
                    "network": f"Network-{number}",
                },
            )
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connection_ambiguous"]
        assert result["connected_device"] == result["connected_port"] == ""
        assert jobs.connection_options(db, row) == {"interfaces": [], "integrations": [], "vm_conflict": True}
        for observation in service.observations(db, [row])[row.id]:
            if observation.source == "vcenter":
                observation.observed_at = now() - timedelta(hours=25)
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""


def test_vcenter_resolves_backing_names_from_later_inventory_pages(monkeypatch):
    from pyVim import connect
    from pyVmomi import vim

    calls = []
    view = vim.view.ContainerView("view-1")
    ds = vim.DistributedVirtualSwitch("dvs-1")
    host = vim.HostSystem("host-1")
    card = vim.vm.device.VirtualVmxnet3(
        key=4000,
        macAddress="00:50:56:a0:42:c0",
        backing=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
            port=vim.dvs.PortConnection(switchUuid="uuid-1", portgroupKey="pg-1", portKey="89")
        ),
    )

    def obj(ref, values):
        return SimpleNamespace(
            obj=ref, missingSet=[], propSet=[SimpleNamespace(name=k, val=v) for k, v in values.items()]
        )

    pages = [
        SimpleNamespace(
            token="next",
            objects=[
                obj(vim.VirtualMachine("vm-1"), {"config.hardware.device": [card], "runtime.host": host})
            ],
        ),
        SimpleNamespace(
            token="",
            objects=[
                obj(ds, {"name": "FBU-DS", "uuid": "uuid-1"}),
                obj(
                    vim.dvs.DistributedVirtualPortgroup("pg-1"),
                    {"name": "VLAN-020", "config.key": "pg-1", "config.distributedVirtualSwitch": ds},
                ),
                obj(host, {"name": "esxi.test"}),
            ],
        ),
    ]
    collector = SimpleNamespace(
        RetrievePropertiesEx=lambda **_: pages[0], ContinueRetrievePropertiesEx=lambda **_: pages[1]
    )
    content = SimpleNamespace(
        rootFolder=vim.Folder("root"),
        propertyCollector=collector,
        viewManager=SimpleNamespace(CreateContainerView=lambda *_: view),
    )
    si = SimpleNamespace(RetrieveContent=lambda: content)
    monkeypatch.setattr(adapters, "connect_vcenter", lambda *_: si)
    monkeypatch.setattr(vim.view.ContainerView, "Destroy", lambda _: calls.append("destroy"))
    monkeypatch.setattr(connect, "Disconnect", lambda _: calls.append("disconnect"))
    result = adapters.vcenter_records(None, None)
    assert result[0]["dvswitch_name"] == "FBU-DS"
    assert result[0]["network"] == "VLAN-020" and result[0]["dvport"] == "89"
    assert result[0]["vm_host_name"] == "esxi.test"
    assert calls == ["destroy", "disconnect"]
    pages[1].objects[0].missingSet = ["permission denied"]
    with pytest.raises(adapters.NetworkError):
        adapters.vcenter_records(None, None)
    assert calls == ["destroy", "disconnect", "destroy", "disconnect"]
