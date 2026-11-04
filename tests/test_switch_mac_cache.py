"""Indexed fallback respects original evidence, VLAN/VRF, source health and port safety."""

from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import mac_cache
from sqlalchemy import delete, select
from test_ipam_source_contract import MAC, read
from test_ipam_source_contract import network as network


def cache(network, *, which=1, port="Gi1/0/9", evidence=None):
    sf, _, _, ids = network
    with sf() as db:
        device = db.get(m.Device, ids[which])
        source = db.scalar(select(m.Observation).where(m.Observation.device_id == device.id))
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device.id))
        data = deepcopy(state.evidence) if evidence is None else deepcopy(evidence)
        data["interfaces"][0]["name"] = port
        profile = db.get(m.Credential, device.snmp_credential_id)
        result = mac_cache.save_snapshot(
            db, device, profile, source.job_id if source else db.scalar(select(m.Job.id)), data
        )
        db.commit()
        return result


def clear_primary_switches(network):
    sf, _, _, ids = network
    with sf() as db:
        # The read journal is not another source snapshot. Clearing it must
        # leave the sole canonical FDB and protocol rows available to all readers.
        db.execute(delete(m.Observation).where(m.Observation.device_id.in_(ids[1:])))
        db.commit()


def test_inventory_and_ipam_share_latest_canonical_fdb(network):
    cache(network)
    assert read(network)["connected_port"] == "Gi1/0/9"
    clear_primary_switches(network)
    result = read(network)
    assert result["connected_device"] == "Access" and result["connected_port"] == "Gi1/0/9"
    assert result["mac_address"] == MAC and result["field_sources"]["mac_address"] == "gateway"
    assert result["connections"][0]["source"] == "gateway+vlan_fdb"


def test_snapshot_diffs_port_moves_and_successful_empty_removes_old_bindings(network):
    cache(network)
    sf, _, _, ids = network
    with sf() as db:
        source = deepcopy(
            db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1])).evidence
        )
        original_id = db.scalar(
            select(m.SwitchMacEntry.id)
            .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
            .where(m.IPAMNetworkState.device_id == ids[1])
        )
    result = cache(network, port="Gi1/0/10")
    assert result["added"] == result["removed"] == 1
    clear_primary_switches(network)
    assert read(network)["connected_port"] == "Gi1/0/10"
    with sf() as db:
        assert db.get(m.SwitchMacEntry, original_id) is None
        retained_id = db.scalar(
            select(m.SwitchMacEntry.id)
            .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
            .where(m.IPAMNetworkState.device_id == ids[1])
        )
    cache(network, port="Gi1/0/10", evidence=source)
    with sf() as db:
        assert (
            db.scalar(
                select(m.SwitchMacEntry.id)
                .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
                .where(m.IPAMNetworkState.device_id == ids[1])
            )
            == retained_id
        )
    source["tables"] = {k: {} for k in mac_cache.REQUIRED}
    cache(network, evidence=source)
    assert read(network)["connected_port"] == ""
    with sf() as db:
        assert not db.scalar(
            select(m.SwitchMacEntry.id)
            .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
            .where(m.IPAMNetworkState.device_id == ids[1])
        )


@pytest.mark.parametrize(
    "fault",
    [
        "expired",
        "failed",
        "incomplete",
        "profile_changed",
        "management_changed",
        "archived",
        "wrong_vlan",
        "wrong_vrf",
        "no_gateway",
    ],
)
def test_invalid_secondary_proof_is_never_displayed(network, fault):
    cache(network)
    clear_primary_switches(network)
    sf, _, _, ids = network
    with sf() as db:
        state = db.scalar(select(m.SwitchMacSnapshot).where(m.SwitchMacSnapshot.device_id == ids[1]))
        device = db.get(m.Device, ids[1])
        if fault == "expired":
            state.observed_at = now() - mac_cache.FRESHNESS - timedelta(seconds=1)
        elif fault in ("failed", "incomplete"):
            mac_cache.save_snapshot(
                db,
                device,
                db.get(m.Credential, device.snmp_credential_id),
                state.job_id,
                {},
                error="NetworkError" if fault == "failed" else "",
            )
        elif fault == "profile_changed":
            db.get(m.Credential, device.snmp_credential_id).updated_at = now() + timedelta(seconds=1)
        elif fault == "management_changed":
            device.management_ip = "198.51.100.99"
        elif fault == "archived":
            device.archived = True
        elif fault == "wrong_vlan":
            db.scalar(
                select(m.SwitchMacEntry)
                .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
                .where(m.IPAMNetworkState.device_id == ids[1])
            ).vlan_vid = 21
        elif fault == "wrong_vrf":
            vrf = m.VRF(name="Other")
            db.add(vrf)
            db.flush()
            db.scalar(
                select(m.SwitchMacEntry)
                .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
                .where(m.IPAMNetworkState.device_id == ids[1])
            ).vrf_id = vrf.id
        elif fault == "no_gateway":
            db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[0])).evidence = {
                "tables": {"arp_mac": {}, "arp_type": {}}
            }
        db.commit()
    assert read(network)["connected_port"] == ""


@pytest.mark.parametrize(
    "fault", ["multiple_macs", "uplink", "unknown_uplink", "shared_fid", "down", "missing_mapping"]
)
def test_cached_fdb_safety_matches_primary_rules(network, fault):
    sf, _, _, ids = network
    with sf() as db:
        data = deepcopy(
            db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1])).evidence
        )
    port = "Gi1/0/9"
    if fault == "multiple_macs":
        data["tables"]["vlan_fdb_port"]["700.0.17.34.51.68.86"] = "9"
        data["tables"]["vlan_fdb_status"]["700.0.17.34.51.68.86"] = "3"
    if fault in ("uplink", "unknown_uplink"):
        data["neighbors"] = [
            {"interface_name": port if fault == "uplink" else "unknown", "remote_name": "bridge"}
        ]
    if fault == "shared_fid":
        data["tables"]["vlan_fdb_id"]["0.21"] = "700"
    if fault == "down":
        data["interfaces"][0]["oper_status"] = "down"
    if fault == "missing_mapping":
        data["tables"]["bridge_ifindex"] = {}
    cache(network, evidence=data)
    clear_primary_switches(network)
    assert read(network)["connected_port"] == ""


def test_manual_connection_and_ambiguous_primary_are_not_replaced(network):
    cache(network)
    sf, _, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        db.commit()
    assert read(network)["connection_ambiguous"] and read(network)["connected_port"] == ""
    clear_primary_switches(network)
    with sf() as db:
        db.get(m.IPAddress, row_id).device_id = ids[2]
        db.commit()
    result = read(network)
    assert result["manual_connection"] and result["connected_port"] == ""


def test_manual_mac_is_display_only_and_does_not_drive_cache_lookup(network):
    cache(network)
    clear_primary_switches(network)
    sf, _, row_id, _ = network
    with sf() as db:
        db.get(m.IPAddress, row_id).mac_address = "00:11:22:33:44:99"
        db.commit()
    result = read(network)
    assert result["mac_address"].endswith(":99") and result["connected_port"] == "Gi1/0/9"


def test_multiple_cached_candidates_stay_ambiguous_until_typed_nic_identity_proves_group(network):
    sf, _, _, ids = network
    with sf() as db:
        payloads = [
            deepcopy(db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == id)).evidence)
            for id in ids[1:]
        ]
        db.execute(delete(m.Link))
        for payload in payloads:
            payload["neighbors"] = []
        db.commit()
    cache(network, which=1, port="A1", evidence=payloads[0])
    cache(network, which=2, port="B2", evidence=payloads[1])
    clear_primary_switches(network)
    assert read(network)["connection_ambiguous"] and not read(network)["connected_device"]
    for which, port, nic in ((1, "A1", "eth0"), (2, "B2", "eth1")):
        payload = payloads[which - 1]
        payload["neighbors"] = [
            {
                "interface_name": port,
                "remote_name": "server",
                "remote_port": nic,
                "source": "lldp",
                "evidence": {
                    "lldp": {
                        "chassis_subtype": 7,
                        "chassis_id": "0461e729-cc05-4eaa-a3a3-e56b01347891",
                        "management_address": "192.0.2.10" if which == 1 else "",
                    }
                },
            }
        ]
        cache(network, which=which, port=port, evidence=payload)
    result = read(network)
    assert not result["connection_ambiguous"]
    assert [(g["device_name"], g["port_label"]) for g in result["connection_groups"]] == [
        ("Access", "A1"),
        ("Core", "B2"),
    ]
