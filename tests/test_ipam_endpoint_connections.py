from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.ipam import adapters, jobs, service


def endpoint(db, vrf_id):
    prefix = m.Prefix(cidr="192.0.2.0/24", vrf_id=vrf_id)
    db.add(prefix)
    db.flush()
    row = service.observe(db, prefix, "192.0.2.11", "inventory", "gw", {"mac_address": "00:50:56:a0:42:c0"})
    return prefix, row


def switch(db, vrf_id, name, uplink=False):
    device = m.Device(
        name=name, management_ip=f"192.0.2.{20 if uplink else 21}", vrf_id=vrf_id, kind="switch"
    )
    db.add(device)
    db.flush()
    port = m.Interface(device_id=device.id, name="Gi1/0/24" if uplink else "Gi1/0/7", if_index=7)
    job = m.Job(kind="discovery", target_id=device.id)
    db.add_all([port, job])
    db.flush()
    db.add(
        m.Observation(
            job_id=job.id,
            device_id=device.id,
            address=device.management_ip,
            evidence={
                "tables": {"fdb_port": {"0.80.86.160.66.192": "3"}, "bridge_ifindex": {"3": "7"}},
                "neighbors": [{"interface_name": port.name}] if uplink else [],
            },
        )
    )
    db.flush()
    return port


def test_vm_connection_wins_over_physical_fdb_and_manual_port(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        port = switch(db, prefix.vrf_id, "Transit", uplink=True)
        row.interface_id = port.id
        config = m.Integration(
            name="vCenter",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            prefix_ids=[prefix.id],
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


def test_physical_leaf_wins_over_transit_and_ambiguity_is_not_a_device_list(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        switch(db, prefix.vrf_id, "Transit", uplink=True)
        switch(db, prefix.vrf_id, "Access")
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "Access" and result["connected_port"] == "Gi1/0/7"
        assert not result["connection_ambiguous"]
        assert len(jobs.connection_options(db, row)["interfaces"]) == 1
        # A second access location is unresolved, not two connected switches.
        second = m.Device(name="Other", management_ip="192.0.2.22", vrf_id=prefix.vrf_id)
        db.add(second)
        db.flush()
        port = m.Interface(device_id=second.id, name="1", if_index=1)
        db.add(port)
        db.flush()
        context = service.connection_context(db)
        context["devices"][second.id] = second
        context["ports"][port.id] = port
        context["indexed"][(prefix.vrf_id, "00:50:56:a0:42:c0")][port.id] = {
            "interface_id": port.id,
            "source": "arp/ndp+fdb",
            "uplink": False,
            "confidence": 0.8,
            "ambiguous": False,
        }
        candidates = service.connection_candidates(db, row, context=context)
        assert all(c["ambiguous"] for c in candidates)
        assert service.physical_connections(candidates) == []


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


async def test_inventory_mac_matches_vm_without_guest_ip_and_removed_nic_is_retired(
    admin_client, inventory, env, monkeypatch
):
    import json

    from netrix.identity.security import encrypt

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        prefix.scan_authorized = True
        config = m.Integration(
            name="VC",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            prefix_ids=[prefix.id],
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


def test_aggregate_uplink_is_not_an_endpoint_port(admin_client, inventory, env):
    from sqlalchemy import select

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        trunk = switch(db, prefix.vrf_id, "Core", uplink=True)
        trunk.name = "Trk1"
        snapshot = db.scalar(select(m.Observation).where(m.Observation.device_id == trunk.device_id))
        snapshot.evidence = {
            **snapshot.evidence,
            "neighbors": [{"interface_name": "A1", "evidence": {"local_aggregate": {"name": "Trk1"}}}],
            "neighbor_detail": {"trunks": {"A1": {"name": "Trk1"}}, "spanning_tree": {"port": "Trk1"}},
        }
        switch(db, prefix.vrf_id, "Access")
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "Access"
        assert result["connected_port"] == "Gi1/0/7"


def test_conflicting_vm_attachments_never_fall_back_to_a_physical_hop(admin_client, inventory, env):
    from datetime import timedelta

    from netrix.core import now

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        switch(db, prefix.vrf_id, "Access")
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
        assert service.enrich(db, [row])[0]["connected_device"] == "Access"


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
