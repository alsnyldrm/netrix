"""Disposable MariaDB: target SNMP facts reuse canonical FID rows and result refs."""

from netrix import models as m
from netrix.core import Base, engine, now, session_factory
from netrix.inventory.device_types import seed_defaults
from netrix.ipam.pipeline import save_result
from netrix.sources.point import switch
from sqlalchemy import func, select

assert engine().url.database == "netrix_test", "Disposable database required"
Base.metadata.create_all(engine())
with session_factory()() as db:
    seed_defaults(db)
    vrf = m.VRF(name="FID fixture")
    db.add(vrf)
    db.flush()
    vlan = m.VLAN(name="Target", vid=60, cidr="192.0.2.0/24", vrf_id=vrf.id)
    device = m.Device(name="Edge", management_ip="198.51.100.2", vrf_id=vrf.id, kind="switch")
    db.add_all([vlan, device])
    db.flush()
    row = m.IPAddress(address="192.0.2.10", vrf_id=vrf.id, vlan_id=vlan.id)
    state = m.IPAMNetworkState(device_id=device.id, address=device.management_ip, observed_at=now())
    db.add_all([row, state])
    db.flush()
    mac = "00:11:22:33:44:55"
    fact = m.SwitchMacEntry(
        snapshot_id=state.id,
        vrf_id=vrf.id,
        vlan_vid=0,
        fdb_id=700,
        mac_address=mac,
        port="1/1/1",
        if_index=101,
        bridge_port=9,
        status="3",
        observed_at=now(),
        present=True,
    )
    db.add(fact)
    db.commit()
    original_id = fact.id
    for _ in range(3):
        switch(
            db,
            device,
            vlan,
            mac,
            [{"port": "1/1/1", "if_index": 101, "bridge_port": 9, "fdb_id": 700, "vlan_unmapped": True}],
            [],
        )
        save_result(
            db,
            row,
            now(),
            {
                "status": "success",
                "values": {
                    "mac_address": mac,
                    "connected_device": "Edge",
                    "connected_port": "1/1/1",
                    "connection_type": "physical",
                    "connections": [
                        {
                            "device_id": device.id,
                            "device_name": "Edge",
                            "port": "1/1/1",
                            "source": "gateway+snmp_fdb",
                            "confidence": 0.85,
                        }
                    ],
                },
                "issues": [],
                "steps": [],
            },
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(m.SwitchMacEntry)) == 1
        assert db.scalar(select(func.count()).select_from(m.SourceVLANFDB)) == 0
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1
        entry = db.scalar(select(m.SwitchMacEntry))
        assert (entry.id, entry.fdb_id, entry.vlan_vid, entry.bridge_port) == (original_id, 700, 0, 9)
        assert db.scalar(select(m.ResolutionConnection)).mac_port_id == original_id
print("PASS: MariaDB canonical MAC/FID identity, no fabricated VLAN mapping, one result and FK reuse")
