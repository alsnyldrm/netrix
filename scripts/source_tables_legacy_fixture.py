"""Run with release-49 models in a disposable database; never contacts devices."""

from datetime import timedelta

from netrix import models as m
from netrix.core import Base, engine, now, session_factory
from sqlalchemy import text

assert engine().url.database == "netrix_test" or str(engine().url.database).endswith("netrix_test.db")
Base.metadata.create_all(engine())
with engine().begin() as c:
    c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    c.execute(text("INSERT INTO alembic_version VALUES ('20261104_49')"))
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    vrf = m.VRF(id="vrf", name="Fixture")
    profile = m.Credential(
        id="profile", name="Fixture SNMP", protocol="snmpv3", encrypted_secret="fixture-unused"
    )
    db.add_all([vrf, profile])
    db.flush()
    scope = m.Scope(id="scope", name="Fixture", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=profile.id)
    vlan = m.VLAN(id="vlan", name="SERVER", vid=20, cidr="192.0.2.0/24", vrf_id=vrf.id)
    db.add_all([scope, vlan])
    db.flush()
    switch = m.Device(
        id="switch",
        name="BB-01",
        management_ip="192.0.2.2",
        kind="switch",
        vrf_id=vrf.id,
        discovery_scope_id=scope.id,
        snmp_credential_id=profile.id,
    )
    ip = m.IPAddress(
        id="ip",
        address="192.0.2.10",
        vrf_id=vrf.id,
        vlan_id=vlan.id,
        hostname="MANUAL",
        operating_system="MANUAL-OS",
    )
    dhcp = m.Integration(
        id="dhcp",
        name="DHCP",
        kind="windows_dhcp",
        host="192.0.2.3",
        port=5985,
        encrypted_secret="fixture-unused",
    )
    vc = m.Integration(
        id="vc", name="vCenter", kind="vcenter", host="192.0.2.4", port=443, encrypted_secret="fixture-unused"
    )
    job = m.Job(id="job", kind="discover", target_id=scope.id, status="succeeded")
    db.add_all([switch, ip, dhcp, vc, job])
    db.flush()
    peer = dict(
        interface_name="A7",
        remote_name="server.example",
        remote_port="vmnic0",
        source="lldp+cdp",
        evidence={
            "lldp": {
                "system_name": "server.example",
                "port_id": "vmnic0",
                "management_address": "192.0.2.10",
            },
            "cdp": {"device_id": "server.example", "port_id": "vmnic0", "management_address": "192.0.2.10"},
        },
    )
    data = dict(
        hostname="BB-01",
        interfaces=[{"if_index": 7, "name": "A7", "oper_status": "up"}],
        neighbors=[peer],
        neighbor_protocols_complete=["lldp", "cdp"],
        unsupported=[],
        tables={
            "vlan_fdb_id": {"0.20": "700"},
            "vlan_fdb_port": {"700.0.17.34.51.68.85": "7"},
            "vlan_fdb_status": {"700.0.17.34.51.68.85": "3"},
            "bridge_ifindex": {"7": "7"},
        },
    )
    db.add(
        m.Observation(
            id="read",
            job_id=job.id,
            device_id=switch.id,
            address=switch.management_ip,
            source="snmpv3",
            evidence=data,
        )
    )
    db.add(m.Link(id="neighbor", device_id=switch.id, last_seen_at=now(), **peer))
    successful_at = now()
    snapshot = m.SwitchMacSnapshot(
        id="mac-read",
        device_id=switch.id,
        observed_at=successful_at,
        attempted_at=successful_at + timedelta(seconds=10),
        healthy=False,
        error_class="TimeoutError",
        entry_count=1,
        evidence=data,
    )
    db.add(snapshot)
    db.flush()
    db.add(
        m.SwitchMacEntry(
            snapshot_id=snapshot.id,
            vrf_id=vrf.id,
            vlan_vid=20,
            mac_address="00:11:22:33:44:55",
            port="A7",
            if_index=7,
        )
    )
    dns = dict(hostname="server.example")
    vm = dict(
        integration_id="vc",
        vm_id="vm-1",
        nic_key="4000",
        guest_address=ip.address,
        hostname="server.example",
        mac_address="00:11:22:33:44:55",
        operating_system="Linux",
        power_state="poweredOn",
        dvswitch="ds-1",
        dvswitch_name="FBU-DS",
        dvport="89",
        network="VLAN-020",
        portgroup_key="pg-20",
    )
    for id, source, key, value in (
        ("dns", "dns", "system", dns),
        (
            "dhcp-source",
            "windows_dhcp",
            "dhcp",
            {
                "hostname": "server.example",
                "mac_address": "00:11:22:33:44:55",
                "reserved": True,
                "integration_id": "dhcp",
            },
        ),
        ("vm-source", "vcenter", "vc:vm-1:4000", vm),
    ):
        db.add(m.IPObservation(id=id, address_id=ip.id, source=source, source_key=key, data=value))
    db.add(
        m.IPAMResult(
            id="result",
            address_id=ip.id,
            address_scope=[ip.address, vrf.id, vlan.id],
            status="success",
            values={
                "hostname": "server.example",
                "mac_address": vm["mac_address"],
                "operating_system": "Linux",
                "network": "VLAN-020",
                "power_state": "poweredOn",
                "connection_type": "vcenter",
                "field_sources": {
                    "hostname": "vcenter",
                    "mac_address": "vcenter",
                    "operating_system": "vcenter",
                },
                "observations": [
                    {
                        "id": "vm-source",
                        "source": "vcenter",
                        "source_key": "vc:vm-1:4000",
                        "observed_at": now().isoformat(),
                        "data": vm,
                    }
                ],
                # Real legacy records can have a bare virtual switch/port
                # label without a structured connection list.
                "connections": [],
                "connected_device": "FBU-DS",
                "connected_port": "89",
            },
        )
    )
    db.add(
        m.Event(
            kind="ip_observation_change",
            message="Fixture",
            details={"previous": {"hostname": "old"}, "current": dns},
        )
    )
    db.commit()
print("Release-49 fixture created; no protocol reads")
