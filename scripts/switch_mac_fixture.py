"""Disposable source fixtures; no worker, scheduler or actual device access."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("ipam_manual_fixture.py")))
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam import mac_cache  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8241"
settings.cache_clear()
assert "netrix-vlan-browser-" in str(settings().database_url)

with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    credential = db.scalar(select(m.Credential))
    switch = db.scalar(select(m.Device).where(m.Device.name == "Switch 1"))
    switch.snmp_credential_id = credential.id
    gateway = m.Device(
        name="Gateway fixture",
        kind="firewall",
        management_ip="198.51.100.254",
        vrf_id=switch.vrf_id,
        discovery_scope_id=switch.discovery_scope_id,
        snmp_credential_id=credential.id,
    )
    db.add(gateway)
    db.flush()
    job = m.Job(kind=mac_cache.KIND, target_id=mac_cache.TARGET, status="succeeded", progress=1, total=1)
    db.add(job)
    db.flush()
    db.add(
        m.Observation(
            job_id=job.id,
            device_id=gateway.id,
            address=gateway.management_ip,
            source="ipam_network",
            evidence={
                "tables": {
                    "arp_mac": {"40.192.0.2.13": "00:11:22:33:44:55"},
                    "ip_addr_ifindex": {"192.0.2.1": "40"},
                    "ip_addr_mask": {"192.0.2.1": "255.255.255.0"},
                },
                "interfaces": [],
                "neighbors": [],
            },
        )
    )
    observe(db, vlan, "192.0.2.13", "icmp", vlan.id, {"reachability": "reachable"})
    observe(db, vlan, "192.0.2.13", "dns", vlan.dns_server_id, {"hostname": "cache-endpoint.example.test"})
    db.commit()


def move(port):
    with session_factory()() as db:
        switch = db.scalar(select(m.Device).where(m.Device.name == "Switch 1"))
        profile = db.get(m.Credential, switch.snmp_credential_id)
        job = db.scalar(select(m.Job).where(m.Job.kind == mac_cache.KIND))
        data = {
            "tables": {
                "vlan_fdb_id": {"0.20": "700"},
                "vlan_fdb_port": {"700.0.17.34.51.68.85": "9"},
                "vlan_fdb_status": {"700.0.17.34.51.68.85": "3"},
                "bridge_ifindex": {"9": "101"},
            },
            "interfaces": [{"if_index": 101, "name": port, "oper_status": "up"}],
            "neighbors": [],
            "neighbor_protocols_complete": ["lldp"],
        }
        mac_cache.save_snapshot(db, switch, profile, job.id, data)
        db.commit()
    services.publish(ipam_vlan="*")
    return {"port": port}


move("1/1/7")


@main.app.post("/fixture/mac-move")
def fake_move():
    return move("1/1/8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8241, log_level="warning")
