"""A current VMware match derives the cabinet label without changing managed data."""

from datetime import timedelta

import pytest
from conftest import make_vlan
from netrix import models as m
from netrix.core import now
from netrix.ipam import service, table
from test_ipam_source_contract import network as network


@pytest.mark.parametrize(
    "present,age,expected", [(True, 0, "Sanal"), (False, 0, "Physical-02"), (True, 25, "Physical-02")]
)
def test_virtual_cabinet_follows_fresh_vm_presence(env, present, age, expected):
    with env() as db:
        vrf = m.VRF(name="VM cabinet")
        db.add(vrf)
        db.flush()
        vlan = make_vlan(cidr="192.0.2.0/24", vrf_id=vrf.id)
        db.add(vlan)
        db.flush()
        row = m.IPAddress(address="192.0.2.10", vrf_id=vrf.id, vlan_id=vlan.id, cabinet="Physical-02")
        db.add(row)
        db.flush()
        db.add(
            m.IPObservation(
                address_id=row.id,
                source="vcenter",
                source_key="vc:vm-1:4000",
                observed_at=now() - timedelta(hours=age),
                data={"vm_id": "vm-1", "nic_key": "4000", "dvswitch_name": "FBU-DS", "present": present},
            )
        )
        db.commit()
        for details in (True, False):
            item = service.enrich(db, [row], details=details)[0]
            assert item["cabinet"] == expected
            assert item["managed"]["cabinet"] == "Physical-02"
        assert table.addresses(db, vlan, allocated=True)["items"][0]["cabinet"] == expected
        assert row.cabinet == "Physical-02"
        if expected == "Sanal":
            assert table.addresses(db, vlan, q="Sanal")["items"][0]["id"] == row.id


def test_conflicting_gateway_mac_does_not_turn_physical_ip_into_virtual(network):
    # The source-contract fixture has a proven gateway MAC for the same VLAN/IP.
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        row.cabinet = "Physical-03"
        service.observe(
            db,
            db.get(m.VLAN, vlan_id),
            row.address,
            "vcenter",
            "vc:vm-old",
            {"vm_id": "vm-old", "mac_address": "00:11:22:33:44:99"},
        )
        db.commit()
        assert service.enrich(db, [row])[0]["cabinet"] == "Physical-03"
