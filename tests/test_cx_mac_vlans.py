from copy import deepcopy

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.discovery.cx_mac import parse_mac_vlans
from netrix.identity.security import encrypt
from netrix.ipam.connections import Evidence
from netrix.ipam.network import read_context
from netrix.sources.network import read
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network

OUTPUT = """MAC age-time : 300 seconds
Number of MAC addresses : 1
MAC Address          VLAN  Type                   Port
------------------------------------------------------
00:11:22:33:44:55    20    port-access-security   1/1/19
"""


def test_parse_explicit_vlan_and_port():
    assert parse_mac_vlans(OUTPUT) == {(MAC, "1/1/19"): 20}


@pytest.mark.parametrize(
    "output",
    [
        OUTPUT.replace("Number of MAC addresses : 1", "Number of MAC addresses : 2"),
        OUTPUT + "malformed row\n",
        "Permission denied",
        OUTPUT.replace("VLAN", "FID"),
    ],
)
def test_truncation_permissions_and_unknown_format_are_not_empty_success(output):
    with pytest.raises(Exception):
        parse_mac_vlans(output)


def test_multiple_vlans_for_same_mac_port_are_not_selected():
    output = OUTPUT.replace("addresses : 1", "addresses : 2") + ("00:11:22:33:44:55 30 dynamic 1/1/19\n")
    assert parse_mac_vlans(output) == {}


def setup_access(db, ids):
    device = db.get(m.Device, ids[1])
    device.adapter = "aruba_6100"
    ssh = m.Credential(
        name="CX read only",
        protocol="ssh",
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
    )
    db.add(ssh)
    db.flush()
    device.config_credential_id = ssh.id
    state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device.id))
    data = deepcopy(read(state))
    data["tables"]["vlan_fdb_id"] = {}
    data.pop("_explicit_fdb_vlans", None)
    data.pop("table_reads", None)
    data["unsupported"] = []
    data["tables"]["if_name"] = {"101": "1/1/19"}
    data["interfaces"][0]["name"] = "1/1/19"
    data["read_context"] = read_context(device, db.get(m.Credential, device.snmp_credential_id), ssh)
    return device, ssh, data


@pytest.mark.parametrize("case", ["valid", "other_mac", "other_port", "shared_fid", "profile_changed"])
def test_inventory_persists_only_correlated_explicit_vlan(network, case):
    sf, vid, rid, ids = network
    with sf() as db:
        device, ssh, data = setup_access(db, ids)
        parsed = parse_mac_vlans(OUTPUT)
        if case == "other_mac":
            parsed = {("00:11:22:33:44:66", "1/1/19"): 20}
        if case == "other_port":
            parsed = {(MAC, "1/1/18"): 20}
        if case == "shared_fid":
            data["tables"]["vlan_fdb_id"] = {"0.20": "700", "0.30": "700"}
        data["cx_mac_vlans"] = parsed
        job = m.Job(kind="discovery", target_id=device.discovery_scope_id)
        db.add(job)
        db.flush()
        db.add(
            m.Observation(
                device_id=device.id,
                address=device.management_ip,
                job_id=job.id,
                source="snmpv3",
                evidence=data,
            )
        )
        db.commit()
        if case == "profile_changed":
            ssh.updated_at = now()
            db.commit()
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device.id))
        assert not state.vlan_fdbs if case != "shared_fid" else len(state.vlan_fdbs) == 2
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        proof = Evidence(db, {vlan.vrf_id}).resolve(row, vlan, identity_mac=MAC)
        assert bool(proof["connections"]) == (case == "valid")
        if case == "valid":
            assert [(c["device_id"], c["port"]) for c in proof["connections"]] == [(device.id, "1/1/19")]
            assert state.mac_entries[0].vlan_vid == 20


@pytest.mark.parametrize("failure", [False, True])
async def test_inventory_worker_invokes_optional_reader_not_ipam(network, monkeypatch, failure):
    sf, vid, rid, ids = network
    with sf() as db:
        device, ssh, data = setup_access(db, ids)
        scope = db.get(m.Scope, device.discovery_scope_id)
        scope.cidr = device.management_ip + "/32"
        data["identity"] = {"name": "Access", "kind": "switch"}
        job = m.Job(kind="discovery", target_id=scope.id, status="running")
        db.add(job)
        db.commit()
        jid = job.id
        did = device.id

    class Collector:
        async def collect(self, *_):
            return deepcopy(data)

    calls = []

    async def cli(device, secret):
        calls.append(device.id)
        if failure:
            raise TimeoutError()
        return parse_mac_vlans(OUTPUT)

    monkeypatch.setattr(worker, "fetch_mac_vlans", cli)
    await worker.discover(jid, Collector())
    assert calls == [did]
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == did))
        assert any(e.mac_address == MAC for e in state.mac_entries)
        assert any(e.mac_address == MAC and e.vlan_vid == 20 for e in state.mac_entries) == (not failure)
        assert state.healthy
        if failure:
            assert any(t.name == "cx_mac_vlan" and t.status == "error" for t in state.unsupported)


def test_failed_cli_keeps_verified_row_and_original_proof_time(network):
    from datetime import timedelta

    sf, vid, rid, ids = network
    with sf() as db:
        device, ssh, data = setup_access(db, ids)
        data["cx_mac_vlans"] = parse_mac_vlans(OUTPUT)
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device.id))
        first_at = now()
        state.observed_at = first_at
        state.evidence = data
        db.commit()
        assert state.mac_entries[0].vlan_vid == 20
        first_time = state.mac_entries[0].observed_at
        later = deepcopy(read(state))
        later["cx_mac_vlan_error"] = "TimeoutError"
        later.pop("cx_mac_vlans", None)
        later.pop("table_reads", None)
        later["unsupported"] = []
        state.observed_at = first_at + timedelta(seconds=10)
        state.evidence = later
        db.commit()
        assert state.mac_entries[0].vlan_vid == 20
        assert state.mac_entries[0].observed_at == first_time
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        proof = Evidence(db, {vlan.vrf_id}).resolve(row, vlan, identity_mac=MAC)
        assert [(c["device_id"], c["port"]) for c in proof["connections"]] == [(device.id, "1/1/19")]
