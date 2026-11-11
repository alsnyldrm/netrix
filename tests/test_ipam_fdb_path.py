from netrix import models as m
from netrix.core import now
from netrix.ipam.inventory_sources import attachment, point_evidence
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network  # noqa: PLC0414


def test_backbone_path_keeps_multi_mac_access_port(network):
    sf, vid, rid, ids = network
    with sf() as db:
        db.get(m.Device, ids[2]).name = "HP-SW-BB-01"
        access = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        access.mac_entries.append(
            m.SwitchMacEntry(
                vrf_id=access.mac_entries[0].vrf_id,
                vlan_vid=20,
                fdb_id=700,
                mac_address="00:11:22:33:44:66",
                port="Gi1/0/1",
                if_index=101,
                bridge_port=9,
            )
        )
        db.add(
            m.Link(
                device_id=ids[1],
                interface_name="Gi1/0/1",
                source="lldp",
                remote_name="Phone",
                remote_port="00:11:22:33:44:66",
                last_seen_at=now(),
            )
        )
        db.commit()
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        for evidence in (None, point_evidence(db, row, vlan, MAC)):
            result = attachment(db, row, vlan, MAC, evidence=evidence)
            assert [(c["device_id"], c["port"]) for c in result["connections"]] == [(ids[1], "Gi1/0/1")]

        # Without the verified backbone hop the unrelated access record cannot win.
        link = db.scalar(select(m.Link).where(m.Link.device_id == ids[2]))
        link.remote_device_id = None
        link.evidence = {"spanning_tree": {"port": link.interface_name}}
        db.commit()
        assert not attachment(db, row, vlan, MAC)["connections"]
