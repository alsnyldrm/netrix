"""Synthetic variants of the reported AOS-S detail fields; no live device access."""

import pytest
from netrix.discovery.aruba import read_neighbor_detail
from netrix.discovery.neighbor_detail import enrich_neighbors, parse_detail, parse_root, parse_trunks
from netrix.discovery.neighbors import parse_neighbors
from test_aruba_adapters import Connection, Shell
from test_neighbor_evidence import h3_tables

CDP = """CDP neighbors information
 Port : A1
 Device ID : 08 f1 ea 65 42 00
 Address Type : IP
 Address : 192.0.2.21
 Device Port : I4
 Port : B1
 Device ID : 08 f1 ea 65 42 00
 Address : 192.0.2.21
 Device Port : D2
"""
LLDP = """LLDP Remote Device Information Detail
 Local Port : A1
 ChassisType : mac-address
 ChassisId : 08f1ea-654200
 PortType : local
 PortId : 260
 SysName : core
 PortDescr : I4
 Remote Management Address
 Type : ipv4
 Address : 192.0.2.21
 Local Port : B1
 ChassisType : mac-address
 ChassisId : 08f1ea-654200
 PortType : local
 PortId : 98
 SysName : core
 PortDescr : D2
 Address : 192.0.2.21
"""
TRUNKS = """Port | Name Type | Group Type
 A1 | core | LAG SFP+DA3 | Trk1 LACP
 B1 | core | LAG SFP+DA3 | Trk1 LACP
 C17 | server NIC1 | Trk2 LACP
"""
ROOT = "CST Root Port : Trk1\n"


def test_snmp_local_port_id_uses_description_and_cdp_explicit_port():
    tables = h3_tables()
    tables["lldp_port"]["0.227.1"] = "260"
    tables["lldp_port_desc"]["0.227.1"] = "I4"
    tables["cdp_port"]["227.1"] = "I4"
    row = parse_neighbors(tables)[0]
    assert row["remote_port"] == "I4"
    assert row["evidence"]["lldp"]["port_id"] == "260"
    tables["cdp_name"] = {}
    assert parse_neighbors(tables)[0]["remote_port"] == "I4"
    tables["lldp_port_desc"] = {}
    assert parse_neighbors(tables)[0]["remote_port"] == ""  # identifier is not a port name


def test_detail_retains_raw_ids_and_observed_membership():
    rows = enrich_neighbors(
        {"neighbors": parse_detail(CDP, "cdp")},
        {
            "neighbors": parse_detail(LLDP, "lldp"),
            "trunks": parse_trunks(TRUNKS),
            "spanning_tree": parse_root(ROOT),
        },
    )["neighbors"]
    assert [(n["interface_name"], n["remote_port"], n["remote_name"]) for n in rows] == [
        ("A1", "I4", "core"),
        ("B1", "D2", "core"),
    ]
    assert rows[0]["evidence"]["lldp"]["port_id"] == "260"
    assert rows[0]["source"] == "lldp+cdp"
    assert rows[0]["evidence"]["local_aggregate"]["name"] == "Trk1"
    assert rows[0]["evidence"]["spanning_tree"]["port"] == "Trk1"
    assert rows[0]["evidence"]["cdp"]["transport"] == "ssh_detail"


def test_same_port_different_chassis_is_not_merged_and_invalid_root_is_not_invented():
    data = enrich_neighbors(
        {"neighbors": parse_detail(CDP, "cdp")},
        {"neighbors": parse_detail(LLDP.replace("08f1ea-654200", "08f1ea-654299"), "lldp")},
    )
    assert len(data["neighbors"]) == 4
    assert parse_root("STP disabled") is None
    assert parse_root("Root Port : This switch is root")["is_root"] is True
    assert parse_root("Root Port : unavailable value") is None


async def test_shell_reads_detail_and_trunks_with_bounded_safe_port_lists():
    shell = Shell(
        {
            "no page": "",
            "show cdp neighbors detail": CDP,
            "show lldp info remote-device": "LocalPort | ChassisId\n A1 | 08f1ea654200\n B1 | 08f1ea654200",
            "show lldp info remote-device A1,B1": LLDP,
            "show trunks": TRUNKS,
            "show spanning-tree": ROOT,
        }
    )
    result = await read_neighbor_detail(Connection(shell), ["A1;write memory", "B1\nreload"])
    assert shell.closed
    assert result["neighbor_protocols_complete"] == ["cdp"]
    assert len(result["neighbors"]) == 2
    assert result["trunks"]["B1"]["name"] == "Trk1"
    assert all("reload" not in command and "write" not in command for command in shell.commands)


async def test_unsupported_commands_do_not_claim_complete_or_guess_trunks():
    shell = Shell(
        {
            command: "Invalid input: fixture"
            for command in (
                "show cdp neighbors detail",
                "show lldp info remote-device",
                "show trunks",
                "show spanning-tree",
            )
        }
        | {"no page": ""}
    )
    result = await read_neighbor_detail(Connection(shell))
    assert result["neighbors"] == result["neighbor_protocols_complete"] == []
    assert "trunks" not in result and "spanning_tree" not in result


def test_corrected_link_reuses_id_and_detail_ip_matches_manually_named_device(env):
    from netrix import models as m
    from netrix.discovery.links import sync_links
    from netrix.services import serialize
    from sqlalchemy import select

    with env() as db:
        vrf = m.VRF(name="detail")
        db.add(vrf)
        db.flush()
        local = m.Device(name="edge", management_ip="192.0.2.20", vrf_id=vrf.id)
        peer = m.Device(name="User managed core name", management_ip="192.0.2.21", vrf_id=vrf.id)
        db.add_all([local, peer])
        db.flush()
        row = parse_detail(LLDP, "lldp")[0]
        old = m.Link(
            device_id=local.id,
            interface_name="A1",
            remote_name="core",
            remote_port="260",
            source="lldp+cdp",
            evidence=row["evidence"],
        )
        db.add(old)
        db.flush()
        old_id = old.id
        # API reads existing evidence correctly even before the next collection.
        assert serialize(old)["remote_port"] == "I4"
        data = enrich_neighbors({"neighbors": [row]}, {"neighbors": parse_detail(CDP, "cdp")})
        sync_links(db, local, data)
        db.flush()
        assert db.get(m.Link, old_id).remote_port == "I4"
        assert old.remote_device_id == peer.id and old.confidence == 0.9
        assert len(list(db.scalars(select(m.Link)))) == 2


@pytest.mark.parametrize("kind", ["identify"])
async def test_worker_collects_detail_even_when_snmp_has_complete_identity(
    admin_client, inventory, env, monkeypatch, kind
):
    from netrix import models as m
    from netrix.worker import claim, execute
    from sqlalchemy import select
    from test_connection_tests import device_with_profiles
    from test_identification import IdentityCollector

    device = device_with_profiles(admin_client, inventory, ["snmpv3", "ssh"])
    with env() as db:
        db.get(m.Device, device["id"]).adapter = "aruba_5400"
        db.commit()
    called = []

    async def detail(target, secret, ports=()):
        assert target.id == device["id"] and secret["password"] == "fixture-password"
        called.append(target.id)
        return {
            "neighbors": parse_detail(LLDP, "lldp"),
            "trunks": parse_trunks(TRUNKS),
            "spanning_tree": parse_root(ROOT),
        }

    monkeypatch.setattr("netrix.worker.fetch_neighbor_detail", detail)
    job = admin_client.post("/api/v1/jobs", json={"kind": kind, "target_id": device["id"]}).json()
    assert claim() == job["id"]
    await execute(job["id"], IdentityCollector({"vendor": "HP", "model": "J9851A", "kind": "switch"}))
    assert called == [device["id"]]
    with env() as db:
        assert db.get(m.Job, job["id"]).status == "succeeded"
        rows = list(db.scalars(select(m.Link).where(m.Link.device_id == device["id"])))
        assert {row.remote_port for row in rows} == {"I4", "D2"}
        assert all(row.evidence["local_aggregate"]["name"] == "Trk1" for row in rows)


@pytest.mark.parametrize("failed_port", [False, True])
async def test_only_complete_global_summary_and_all_details_can_retire_lldp(failed_port):
    shell = Shell(
        {
            "no page": "",
            "show cdp neighbors detail": "Invalid input",
            "show lldp info remote-device": "LLDP Remote Devices Information\nLocalPort | ChassisId\n A1 | 08f1ea654200\n B1 | 08f1ea654200",
            "show lldp info remote-device A1,B1": "Invalid input" if failed_port else LLDP,
            "show trunks": TRUNKS,
            "show spanning-tree": ROOT,
        }
    )
    result = await read_neighbor_detail(Connection(shell))
    assert ("lldp" in result["neighbor_protocols_complete"]) is not failed_port
