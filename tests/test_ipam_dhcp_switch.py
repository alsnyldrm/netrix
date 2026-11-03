"""Verified DHCP display names and explicit Q-BRIDGE other(1) port locations."""

import json
from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import service
from sqlalchemy import delete, select
from test_ipam_source_contract import MAC, SUFFIX, read
from test_ipam_source_contract import network as network

NAME = "CM-KT-A0-03.example.test"


def dhcp(db, vlan, row, **changes):
    return service.observe(
        db,
        vlan,
        row.address,
        "windows_dhcp",
        "dhcp",
        {"hostname": NAME, "mac_address": MAC, "reserved": True, "lease_state": "", **changes},
    )


@pytest.mark.parametrize("reserved,state", [(True, ""), (False, "Active"), (False, "ActiveReservation")])
def test_dhcp_name_and_other_fdb_port_are_visible_together(network, admin_client, reserved, state):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.IPObservation).where(m.IPObservation.source == "dns"))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        dhcp(db, vlan, row, reserved=reserved, lease_state=state, operating_system="not-an-os-source")
        obs = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
        data = deepcopy(obs.evidence)
        data["tables"]["vlan_fdb_status"]["700." + SUFFIX] = "1"
        obs.evidence = data
        db.commit()
    detail = admin_client.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert detail["hostname"] == NAME and detail["field_sources"]["hostname"] == "windows_dhcp"
    assert detail["mac_address"] == MAC and detail["field_sources"]["mac_address"] == "gateway"
    assert detail["operating_system"] == "" and detail["managed"]["hostname"] == ""
    assert detail["connected_device"] == "Access" and detail["connected_port"] == "Gi1/0/1"
    for params in ({"q": NAME}, {"filters": json.dumps([{"field": "hostname", "op": "eq", "value": NAME}])}):
        page = admin_client.get(f"/api/v1/ipam/vlans/{vlan_id}/addresses", params=params).json()
        assert len(page["items"]) == 1 and page["items"][0]["hostname"] == NAME
        assert page["items"][0]["connected_device"] == "Access"
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        service.observe(db, vlan, row.address, "dns", "system", {"hostname": "dns.example"})
        db.commit()
        item = service.enrich(db, [row])[0]
        assert item["hostname"] == "dns.example" and item["field_sources"]["hostname"] == "dns"
        row.hostname = "manual.example"
        db.commit()
        assert service.enrich(db, [row])[0]["hostname"] == "manual.example"


@pytest.mark.parametrize(
    "fault",
    [
        "mac_mismatch",
        "no_gateway",
        "stale",
        "gone",
        "inactive",
        "conflicting_name",
        "conflicting_mac",
        "no_mac",
    ],
)
def test_unverified_dhcp_names_are_not_applied(network, fault):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.IPObservation).where(m.IPObservation.source == "dns"))
        if fault == "no_gateway":
            db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        changes = {}
        if fault == "mac_mismatch":
            changes["mac_address"] = "00:11:22:33:44:99"
        if fault == "no_mac":
            changes["mac_address"] = ""
        if fault == "gone":
            changes["present"] = False
        if fault == "inactive":
            changes.update(reserved=False, lease_state="Expired")
        dhcp(db, vlan, row, **changes)
        if fault in ("conflicting_name", "conflicting_mac"):
            service.observe(
                db,
                vlan,
                row.address,
                "windows_dhcp",
                "dhcp-two",
                {
                    "hostname": "other.example" if fault == "conflicting_name" else NAME,
                    "mac_address": MAC if fault == "conflicting_name" else "00:11:22:33:44:99",
                    "reserved": True,
                },
            )
        if fault == "stale":
            db.scalar(select(m.IPObservation).where(m.IPObservation.source == "windows_dhcp")).observed_at = (
                now() - timedelta(hours=25)
            )
        db.commit()
    assert read(network)["hostname"] == ""


@pytest.mark.parametrize(
    "status,accepted",
    [("1", True), ("3", True), ("5", True), ("2", False), ("4", False), ("", False), ("6", False)],
)
def test_explicit_fdb_port_status_is_interpreted_without_guessing(network, status, accepted):
    sf, _, _, ids = network
    with sf() as db:
        obs = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
        data = deepcopy(obs.evidence)
        data["tables"]["vlan_fdb_status"]["700." + SUFFIX] = status
        obs.evidence = data
        db.commit()
    assert read(network)["connected_port"] == ("Gi1/0/1" if accepted else "")


def test_other_status_macs_still_mark_a_port_as_transit(network):
    sf, _, _, ids = network
    with sf() as db:
        obs = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
        data = deepcopy(obs.evidence)
        other = "700.0.17.34.51.68.86"
        data["tables"]["vlan_fdb_port"][other] = "9"
        data["tables"]["vlan_fdb_status"][other] = "1"
        obs.evidence = data
        db.commit()
    assert read(network)["connected_port"] == ""


@pytest.mark.asyncio
async def test_scheduled_dhcp_snapshot_updates_and_retires_display_name(network, monkeypatch):
    from netrix.identity.security import encrypt
    from netrix.ipam import adapters, jobs

    sf, _, row_id, _ = network
    with sf() as db:
        db.execute(delete(m.IPObservation).where(m.IPObservation.source == "dns"))
        config = m.Integration(
            name="DHCP",
            kind="windows_dhcp",
            host="dhcp.test",
            port=5986,
            enabled=True,
            encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id, result={"ipam_origin": "scheduled_source"})
        db.add(job)
        db.commit()
        job_id = job.id
    records = [{"address": "192.0.2.10", "hostname": NAME, "mac_address": MAC, "reserved": True}]
    monkeypatch.setattr(adapters, "windows_dhcp", lambda *_: records)
    await jobs.integration(job_id)
    assert read(network)["hostname"] == NAME
    records.clear()
    await jobs.integration(job_id)
    item = read(network)
    assert item["hostname"] == "" and item["mac_address"] == MAC
    with sf() as db:
        assert db.get(m.IPAddress, row_id).hostname == ""
