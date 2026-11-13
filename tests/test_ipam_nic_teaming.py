"""NIC-Teaming projects canonical aggregate membership without a separate scan."""

from netrix import models as m
from netrix.ipam.teaming import display_members
from sqlalchemy import select
from test_ipam_source_contract import network as network  # noqa: PLC0414


def test_teaming_displays_multiple_switches_and_trunk_members(network):
    sf, _, _, devices = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == devices[1]))
        state.ports.extend(
            m.SourcePort(if_index=index, name=port, aggregate="Trk3")
            for index, port in ((700, "H7"), (701, "H8"))
        )
        db.flush()
        connections = [
            {"device_id": devices[1], "device_name": "Access", "port": "Trk3"},
            {"device_id": devices[2], "device_name": "Core", "port": "B4"},
        ]
        enabled = {"nic_teaming": True, "connections": connections}
        disabled = {"nic_teaming": False, "connections": connections}
        display_members(db, [enabled, disabled])
        assert enabled["connected_device"] == "Access / Core"
        assert enabled["connected_port"] == "H7 Trk3 - H8 Trk3 / B4"
        assert disabled["connections"] == connections


def test_enabling_teaming_preserves_existing_scan_result(admin_client, network):
    sf, vid, rid, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        db.add(m.IPAMResult(address_id=rid, address_scope=[row.address, row.vrf_id, vid], status="success"))
        db.commit()
        vrf_id = row.vrf_id
    response = admin_client.put(
        f"/api/v1/addresses/{rid}",
        json={"address": "192.0.2.10", "vlan_id": vid, "vrf_id": vrf_id, "nic_teaming": True},
    )
    assert response.status_code == 200, response.text
    with sf() as db:
        assert db.get(m.IPAddress, rid).nic_teaming
        assert db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).status == "success"
