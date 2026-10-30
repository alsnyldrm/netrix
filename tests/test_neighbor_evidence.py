from netrix.discovery.neighbors import parse_neighbors
from pysnmp.proto.rfc1902 import OctetString


def h3_tables():
    return {
        "if_name": {"227": "H3", "228": "H4"},
        "if_descr": {"227": "H3", "228": "H4"},
        "lldp_local_id": {"227": "227"},
        "lldp_local_type": {"227": 7},
        "lldp_local_desc": {"227": "H3"},
        "lldp_name": {"0.227.1": "HP-SW-CO-01-A-09-01"},
        "lldp_chassis_type": {"0.227.1": 4},
        "lldp_chassis": {"0.227.1": OctetString(bytes.fromhex("3821c73cb240"))},
        "lldp_port_type": {"0.227.1": 7},
        "lldp_port": {"0.227.1": "49"},
        "lldp_port_desc": {"0.227.1": "49"},
        "cdp_name": {"227.1": OctetString(bytes.fromhex("3821c73cb240"))},
        "cdp_port": {"227.1": "49"},
    }


def test_h3_lldp_and_cdp_agree_on_real_port_chassis_and_name():
    rows = parse_neighbors(h3_tables())
    assert len(rows) == 1
    assert {k: rows[0][k] for k in ("interface_name", "remote_name", "remote_port", "source")} == {
        "interface_name": "H3",
        "remote_name": "HP-SW-CO-01-A-09-01",
        "remote_port": "49",
        "source": "lldp+cdp",
    }
    assert rows[0]["evidence"]["lldp"]["chassis_id"] == "38:21:c7:3c:b2:40"
    assert rows[0]["evidence"]["cdp"]["device_id"] == "38:21:c7:3c:b2:40"


def test_subtype_decodes_even_printable_mac_and_retains_unnamed_neighbors():
    tables = h3_tables()
    tables["lldp_name"] = {}
    tables["cdp_name"] = {}
    tables["lldp_chassis"]["0.227.1"] = OctetString(b"ABCDEF")
    tables["lldp_port_type"]["0.227.1"] = 3
    tables["lldp_port"]["0.227.1"] = OctetString(b"123456")
    row = parse_neighbors(tables)[0]
    assert row["remote_name"] == "41:42:43:44:45:46"
    assert row["remote_port"] == "31:32:33:34:35:36"


def test_local_lldp_number_is_not_assumed_to_be_ifindex():
    tables = h3_tables()
    tables["lldp_local_desc"] = {"227": "H4"}
    rows = parse_neighbors(tables)
    assert [row["interface_name"] for row in rows] == ["H4", "H3"]
    assert [row["source"] for row in rows] == ["lldp", "cdp"]


def test_shared_local_port_does_not_merge_different_or_ambiguous_chassis():
    tables = h3_tables()
    tables["cdp_name"]["227.1"] = OctetString(bytes.fromhex("3821c73cb241"))
    assert len(parse_neighbors(tables)) == 2
    tables = h3_tables()
    for key in ("lldp_name", "lldp_chassis_type", "lldp_chassis", "lldp_port", "lldp_port_type"):
        tables[key]["0.227.2"] = tables[key]["0.227.1"]
    tables["lldp_port"]["0.227.2"] = "50"
    assert len(parse_neighbors(tables)) == 3


def test_conflicting_advertised_names_are_not_merged():
    tables = h3_tables()
    tables["cdp_sysname"] = {"227.1": "different-peer"}
    assert len(parse_neighbors(tables)) == 2


def test_fresh_snapshot_repairs_legacy_h3_keeps_history_and_manual_links(env):
    from netrix import models as m
    from netrix.core import now
    from netrix.discovery.links import sync_links
    from netrix.services import list_resource
    from sqlalchemy import select

    with env() as db:
        vrf = m.VRF(name="neighbors")
        db.add(vrf)
        db.flush()
        device = m.Device(name="core", management_ip="192.0.2.1", vrf_id=vrf.id)
        db.add(device)
        db.flush()
        raw = bytes.fromhex("3821c73cb240").decode("latin1")
        cdp = m.Link(
            device_id=device.id, interface_name="H3", remote_name=raw, remote_port="49", source="cdp"
        )
        lldp = m.Link(
            device_id=device.id,
            interface_name="227",
            remote_name="HP-SW-CO-01-A-09-01",
            remote_port="49",
            source="lldp",
        )
        manual = m.Link(
            device_id=device.id,
            interface_name="",
            remote_name="firewall",
            remote_port="",
            source="manual",
            confidence=1,
        )
        disappeared = m.Link(
            device_id=device.id,
            interface_name="H8",
            remote_name="old-peer",
            remote_port="1",
            source="cdp",
            last_seen_at=now(),
        )
        db.add_all([cdp, lldp, manual, disappeared])
        db.flush()
        old_seen = disappeared.last_seen_at
        snapshot = {"neighbors": parse_neighbors(h3_tables()), "neighbor_protocols_complete": ["lldp", "cdp"]}
        sync_links(db, device, snapshot)
        db.commit()
        assert cdp.remote_name == "HP-SW-CO-01-A-09-01"
        assert cdp.source == "lldp+cdp" and cdp.is_current
        assert cdp.evidence["lldp"]["chassis_id"] == "38:21:c7:3c:b2:40"
        assert cdp.last_seen_at > old_seen
        assert not lldp.is_current and not disappeared.is_current
        assert disappeared.last_seen_at == old_seen
        assert manual.is_current and manual.confidence == 1
        result = list_resource(db, "links")
        assert result["total"] == 2
        assert all(row["remote_name"] != raw for row in result["items"])
        before = len(list(db.scalars(select(m.Link))))
        sync_links(db, device, snapshot)
        db.commit()
        assert len(list(db.scalars(select(m.Link)))) == before
        # A failed/partial LLDP or CDP walk cannot expire a combined record.
        sync_links(db, device, {"neighbors": [], "neighbor_protocols_complete": ["lldp"]})
        db.commit()
        assert cdp.is_current
        sync_links(db, device, {"neighbors": [], "neighbor_protocols_complete": ["lldp", "cdp"]})
        db.commit()
        assert not cdp.is_current and manual.is_current
        sync_links(db, device, snapshot)
        db.commit()
        assert cdp.is_current  # rediscovery reuses the same record
