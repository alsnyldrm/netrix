"""SNMP collection and canonical SQL integrity regressions; no production IO."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.core import now
from netrix.discovery import protocols as p
from netrix.discovery import table_reads
from netrix.discovery.fid_candidates import candidates
from netrix.sources import network as n
from sqlalchemy import select
from test_ipam_source_contract import network as network


def snap():
    return {
        "tables": {
            "vlan_fdb_id": {"0.20": "700"},
            "vlan_fdb_port": {"700.0.17.34.51.68.85": "9"},
            "vlan_fdb_status": {"700.0.17.34.51.68.85": "3"},
            "bridge_ifindex": {"9": "101"},
        },
        "unsupported": [],
        "interfaces": [{"if_index": 101, "name": "Gi1/0/1", "oper_status": "up"}],
    }


def test_inventory_preserves_verified_status_and_vlan(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        assert (
            state.fdb_complete and state.mac_entries[0].status == "3" and state.mac_entries[0].vlan_vid == 20
        )
        data = snap()
        data["tables"].pop("vlan_fdb_id")
        data["tables"].pop("vlan_fdb_status")
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        assert state.fdb_complete
        assert state.vlan_fdbs[0].fdb_id == 700
        assert state.mac_entries[0].status == "3" and state.mac_entries[0].vlan_vid == 20
        # Retained facts remain last-known; a partial attempt is not fresh proof.
        assert candidates(n.read(state), "00:11:22:33:44:55") == []


def test_partial_table_preserves_and_adds_valid_new_rows(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        data = snap()
        data["tables"]["vlan_fdb_port"]["700.0.17.34.51.68.86"] = "9"
        data["tables"]["vlan_fdb_status"]["700.0.17.34.51.68.86"] = "3"
        data["unsupported"] = ["vlan_fdb_port"]
        old = state.mac_entries[0].observed_at
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
        assert len(state.mac_entries) == 2
        assert all(e.status == "3" for e in state.mac_entries)
        assert state.fdb_at == old and state.fdb_complete


def test_old_read_preserves_newer_vlan_mapping(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        assert state.vlan_fdbs
        at = state.fdb_at
        n.write(db, state, snap(), at - timedelta(minutes=1))
        db.commit()
        assert state.fdb_at == at
        assert state.vlan_fdbs[0].fdb_id == 700


def test_failed_gateway_read_preserves_previous_binding(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[0]))
        fact = db.scalar(select(m.GatewayBinding).where(m.GatewayBinding.device_id == ids[0]))
        assert fact.present
        n.write(
            db,
            state,
            {"tables": {"arp_mac": {}, "ndp_mac": {}}, "unsupported": ["arp_mac", "ndp_mac"]},
            now() + timedelta(seconds=1),
        )
        db.commit()
        assert fact.present


def fake_collector(monkeypatch, rows=1, fault=None):
    seen = []
    monkeypatch.setattr(p, "SnmpEngine", lambda: SimpleNamespace(close_dispatcher=lambda: None))

    async def create(*a, **k):
        return None

    monkeypatch.setattr(p, "UdpTransportTarget", SimpleNamespace(create=create))
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)

    async def get(*a, **k):
        return None, 0, 0, [("x", "fixture"), ("x", "1.3.6.1.4.1.99999"), ("x", 123), ("x", "fixture")]

    monkeypatch.setattr(p, "get_cmd", get)

    async def walk(*a, **k):
        oid = a[-1]
        seen.append(oid)
        key = next((key for key, v in p.IPAM_TABLES.items() if v == oid), "")
        if key == "vlan_fdb_port":
            for i in range(min(rows, k["maxRows"])):
                yield None, 0, 0, [(oid + ".700.0.17.34.51." + str(i // 256) + "." + str(i % 256), 9)]
            if fault == "timeout":
                raise TimeoutError()
            if fault == "pdu":
                yield None, 5, 1, []
            if fault == "exception":
                raise TimeoutError()
        if key == "if_descr" and fault == "if_descr":
            yield None, 5, 1, []
            return
        if key in ("if_name", "if_descr"):
            yield None, 0, 0, [(oid + ".101", "Gi1/0/1")]
        if key == "bridge_ifindex":
            yield None, 0, 0, [(oid + ".9", 101)]
        if key == "vlan_fdb_status":
            yield None, 0, 0, [(oid + ".700.0.17.34.51.0.0", 3)]
        if key == "vlan_fdb_id":
            yield None, 0, 0, [(oid + ".0.20", 700)]

    monkeypatch.setattr(table_reads, "walk_table", walk)
    return seen


async def test_actual_inventory_collector_requests_required_columns(monkeypatch):
    seen = fake_collector(monkeypatch)
    result = await p.SNMPCollector().collect(
        "192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"}
    )
    assert len(result["tables"]["vlan_fdb_port"]) == 1 and result["unsupported"] == []
    assert p.IPAM_TABLES["vlan_fdb_status"] in seen
    assert p.IPAM_TABLES["vlan_fdb_id"] in seen


@pytest.mark.parametrize("fault", ["timeout", "pdu", "limit"])
async def test_distinct_causes_have_distinct_error_markers(monkeypatch, fault):
    fake_collector(monkeypatch, rows=65537 if fault == "limit" else 1, fault=fault)
    result = await p.SNMPCollector().collect(
        "192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"}
    )
    assert result["unsupported"] == ["vlan_fdb_port"]
    assert result["partial"]
    assert (
        result["table_reads"]["vlan_fdb_port"]["status"]
        == {"timeout": "timeout", "pdu": "error", "limit": "truncated"}[fault]
    )
    assert result["tables"]["vlan_fdb_port"]


async def test_timeout_preserves_previously_collected_tables(monkeypatch):
    fake_collector(monkeypatch, fault="exception")
    result = await p.SNMPCollector().collect(
        "192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"}
    )
    assert result["tables"]["bridge_ifindex"]
    assert result["table_reads"]["vlan_fdb_port"]["status"] == "timeout"


def test_existing_mac_updates_ifindex_after_port_reindex(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        data = snap()
        data["interfaces"][0]["if_index"] = 202
        data["tables"]["bridge_ifindex"]["9"] = "202"
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
        assert state.ports[0].if_index == 202
        assert state.mac_entries[0].if_index == 202


def test_missing_mapping_accepts_valid_raw_fdb_in_scheduled_cache(network):
    from netrix.ipam.mac_cache import save_snapshot

    sf, _, _, ids = network
    with sf() as db:
        device = db.get(m.Device, ids[1])
        profile = db.get(m.Credential, device.snmp_credential_id)
        data = snap()
        data["tables"]["vlan_fdb_id"] = {}
        data["unsupported"] = ["vlan_fdb_id"]
        result = save_snapshot(db, device, profile, None, data)
        assert result["read"] == 1 and result["failed"] == 0
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device.id))
        assert state.entry_count == 1


def test_empty_point_result_preserves_previous_fact_without_proof_of_absence(network):
    from netrix.sources.point import switch

    sf, vlan_id, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        assert state.mac_entries[0].present
        switch(db, db.get(m.Device, ids[1]), db.get(m.VLAN, vlan_id), "00:11:22:33:44:55", [], [])
        db.commit()
        assert state.mac_entries[0].present


def test_successful_empty_fdb_retires_only_absent_records(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        data = snap()
        data["tables"]["vlan_fdb_port"] = {}
        data["tables"]["vlan_fdb_status"] = {}
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
        assert not [e for e in state.mac_entries if e.present]
        assert state.fdb_complete


async def test_full_2048_rows_are_not_truncated(monkeypatch):
    fake_collector(monkeypatch, rows=2048)
    data = await p.SNMPCollector().collect("192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"})
    assert data["table_reads"]["vlan_fdb_port"]["status"] == "complete"
    assert len(data["tables"]["vlan_fdb_port"]) == 2048


def test_fdb_quality_survives_identity_only_collection(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        at = state.fdb_at
        n.write(db, state, {"hostname": "new name", "tables": {}}, now() + timedelta(seconds=1))
        db.commit()
        assert state.fdb_complete and state.fdb_at == at
        assert state.vlan_fdbs and state.mac_entries[0].status == "3"


def test_partial_interface_status_does_not_replace_confirmed_up(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        data = snap()
        data["interfaces"][0]["oper_status"] = "unknown"
        data["unsupported"] = ["if_status"]
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
        assert state.ports[0].oper_status == "up"
        assert next(r for r in state.unsupported if r.name == "if_status").status == "error"


def test_missing_row_dependency_cannot_retire_verified_fdb(network):
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        at, fact = state.fdb_at, state.mac_entries[0].id
        data = snap()
        data["tables"]["vlan_fdb_status"] = {}
        n.write(db, state, data, now() + timedelta(seconds=1))
        db.commit()
        assert state.fdb_at == at
        assert len(state.mac_entries) == 1 and state.mac_entries[0].id == fact
        assert state.mac_entries[0].present
        outcome = next(r for r in state.unsupported if r.name == "vlan_fdb_port")
        assert outcome.status == "incomplete" and outcome.error_code == "unresolved_row_dependencies"


async def test_interface_names_survive_missing_description_mib(monkeypatch):
    seen = fake_collector(monkeypatch, fault="if_descr")
    data = await p.SNMPCollector().collect("192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"})
    assert data["interfaces"][0]["name"] == "Gi1/0/1"
    assert "if_descr" in data["unsupported"]
    assert seen.index(p.TABLES["vlan_fdb_port"]) < seen.index(p.TABLES["lldp_name"])


@pytest.mark.parametrize("exception", [p.NoSuchObject(), p.NoSuchInstance()])
async def test_root_oid_exception_is_not_a_successful_empty_table(monkeypatch, exception):
    from netrix.discovery.table_reads import read_table

    oid = p.IPAM_TABLES["vlan_fdb_port"]
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)

    async def walk(*args, **kwargs):
        yield None, 0, 0, [(oid, exception)]

    monkeypatch.setattr(table_reads, "walk_table", walk)
    rows, outcome = await read_table(None, None, None, None, oid)
    assert rows == {} and outcome["status"] == "unsupported"


@pytest.mark.parametrize(
    "ending,status",
    [(p.NoSuchObject(), "unsupported"), (p.NoSuchInstance(), "unsupported"), (p.EndOfMibView(), "complete")],
)
async def test_raw_bulk_preserves_exception_vs_empty_distinction(monkeypatch, ending, status):
    from pysnmp.proto.rfc1902 import ObjectName

    oid = p.IPAM_TABLES["vlan_fdb_port"]

    async def bulk(*args, **kwargs):
        return None, 0, 0, [(ObjectName(oid), ending)]

    monkeypatch.setattr(table_reads, "bulk_cmd", bulk)
    rows, outcome = await table_reads.read_table(None, None, None, None, oid)
    assert rows == {} and outcome["status"] == status


async def test_raw_bulk_repeated_oid_is_error_not_complete(monkeypatch):
    from pysnmp.proto.rfc1902 import Integer32, ObjectName

    oid = p.IPAM_TABLES["vlan_fdb_port"]

    async def bulk(*args, **kwargs):
        return None, 0, 0, [(ObjectName(oid + ".700.0.17.34.51.68.85"), Integer32(9))]

    monkeypatch.setattr(table_reads, "bulk_cmd", bulk)
    rows, outcome = await table_reads.read_table(None, None, None, None, oid)
    assert len(rows) == 1 and outcome["status"] == "error"
