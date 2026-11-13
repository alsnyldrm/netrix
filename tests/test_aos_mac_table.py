import pytest
from sqlalchemy import select

from netrix import models as m
from netrix.configuration.validation import BackupError
from netrix.core import now
from netrix.discovery.aos_mac import parse_mac_table
from netrix.ipam.inventory_sources import attachment
from netrix.sources.network import read, write
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network

OUTPUT = """
Status and Counters - Port Address Table

MAC Address       Port   VLAN
----------------- ------ ----
c46516-28d3d7      G1     180
c4651628d3d7       21     181
00:11:22:33:44:55  Gi1/0/1 20
"""


def test_aos_mac_table_accepts_port_labels_and_mac_formats():
    assert parse_mac_table(OUTPUT) == {
        (180, "c4:65:16:28:d3:d7", "G1"),
        (181, "c4:65:16:28:d3:d7", "21"),
        (20, MAC, "Gi1/0/1"),
    }
    with pytest.raises(BackupError):
        parse_mac_table(OUTPUT + "\n-- MORE --\n")


def test_inventory_persists_cli_only_mac_and_preserves_it_on_failed_read(network):
    sf, vid, rid, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        data = read(state)
        del data["tables"]["vlan_fdb_port"]["700.0.17.34.51.68.85"]
        data["aos_mac_rows"] = {(20, MAC, "Gi1/0/1")}
        write(db, state, data, now())
        db.commit()
        fact = next(e for e in state.mac_entries if e.mac_address == MAC)
        assert (fact.vlan_vid, fact.port, fact.present) == (20, "Gi1/0/1", True)
        observed = fact.observed_at
        del data["aos_mac_rows"]
        data["aos_mac_error"] = "TimeoutError"
        write(db, state, data, now())
        db.commit()
        assert fact.present and fact.observed_at == observed
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        assert attachment(db, row, vlan, MAC)["connected_port"] == "Gi1/0/1"
