"""Disposable host/NIC browser data; no workers and no real device access."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("vlan_configuration_fixture.py")))

from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402
from sqlalchemy import select  # noqa: E402

with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    switches = list(db.scalars(select(m.Device).order_by(m.Device.name)))[:2]
    gateway = m.Device(
        name="Gateway",
        management_ip="198.51.100.254",
        kind="firewall",
        vrf_id=vlan.vrf_id,
        discovery_scope_id=switches[0].discovery_scope_id,
    )
    db.add(gateway)
    job = m.Job(kind="ipam_discover", target_id=vlan.id, status="succeeded")
    db.add(job)
    db.flush()
    neighbors = {switches[0].id: [], switches[1].id: []}
    arp = {}
    for last, pairs in [(20, [(0, "A1"), (0, "B2")]), (21, [(0, "C3"), (1, "D4")])]:
        mac = f"00:11:22:00:00:{last:02x}"
        arp[f"40.192.0.2.{last}"] = mac
        pnics = []
        for n, (switch, port) in enumerate(pairs):
            nic_mac = f"00:22:33:00:{last:02x}:{n:02x}"
            pnics.append(dict(device=f"vmnic{n}", mac_address=nic_mac, link_up=True))
            neighbors[switches[switch].id].append(
                dict(
                    interface_name=port,
                    remote_name=f"esxi-{last}.example.test",
                    remote_port=f"vmnic{n}",
                    source="lldp",
                    evidence={"lldp": {"port_subtype": 3, "port_id": nic_mac}},
                )
            )
        pnics.append(dict(device="vmnic2", mac_address=f"00:22:33:00:{last:02x}:02", link_up=False))
        address = f"192.0.2.{last}"
        observe(db, vlan, address, "dns", vlan.dns_server_id, {"hostname": f"esxi-{last}.example.test"})
        observe(db, vlan, address, "icmp", vlan.id, {"reachability": "reachable"})
        observe(
            db,
            vlan,
            address,
            "vcenter",
            f"vc:host:host-{last}:vmk0",
            dict(
                record_type="host",
                host_id=f"host-{last}",
                host_uuid=f"00000000-0000-0000-0000-0000000000{last}",
                host_address=address,
                hostname=f"esxi-{last}.example.test",
                mac_address=mac,
                vmkernel_device="vmk0",
                physical_nics=pnics,
                operating_system="VMware ESXi 8.0",
            ),
        )
    arp["40.192.0.2.22"] = "00:11:22:00:00:22"
    observe(db, vlan, "192.0.2.22", "dns", vlan.dns_server_id, {"hostname": "physical-host.example.test"})
    observe(db, vlan, "192.0.2.22", "icmp", vlan.id, {"reachability": "reachable"})
    for port, suffix in (("A7", 1), ("B7", 2)):
        neighbors[switches[0].id].append(
            dict(
                interface_name=port,
                remote_name="physical-host",
                remote_port=f"eth{suffix}",
                source="lldp+cdp",
                evidence={
                    "lldp": {
                        "chassis_subtype": 4,
                        "chassis_id": "00:55:66:00:00:01",
                        "port_subtype": 3,
                        "port_id": f"00 55 66 00 00 {suffix + 1:02x}",
                        "transport": "ssh_detail",
                    },
                    "cdp": {
                        "device_id": "00:55:66:00:00:01",
                        "management_address": "192.0.2.22",
                        "port_id": f"eth{suffix}",
                        "transport": "ssh_detail",
                    },
                },
            )
        )
    for switch in switches:
        ns = neighbors[switch.id]
        db.add(
            m.Observation(
                job_id=job.id,
                device_id=switch.id,
                address=switch.management_ip,
                source="ipam_network",
                evidence={
                    "tables": {},
                    "neighbors": ns,
                    "neighbor_protocols_complete": ["lldp", "cdp"],
                    "interfaces": [
                        dict(if_index=i + 1, name=n["interface_name"], oper_status="up")
                        for i, n in enumerate(ns)
                    ],
                },
            )
        )
    db.add(
        m.Observation(
            job_id=job.id,
            device_id=gateway.id,
            address=gateway.management_ip,
            source="ipam_network",
            evidence={
                "tables": {
                    "arp_mac": arp,
                    "ip_addr_ifindex": {"192.0.2.1": "40"},
                    "ip_addr_mask": {"192.0.2.1": "255.255.255.0"},
                }
            },
        )
    )
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
