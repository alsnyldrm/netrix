"""Fresh targeted DNS and positive inventory FDB fallback without an endpoint neighbor."""

from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import adapters, pipeline, sql_sources
from netrix.ipam.inventory_sources import attachment, point_evidence
from netrix.sources.network import read
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("name", ["changed.example", "dns.example"])
async def test_manual_dns_queries_and_refreshes_canonical_hostname(network, monkeypatch, name, configured):
    sf, vid, rid, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        fact = db.scalar(select(m.DNSRecord).where(m.DNSRecord.address_id == rid))
        if configured:
            server = m.DNSServer(name="Test DNS", address="192.0.2.53")
            db.add(server)
            db.flush()
            vlan.dns_server_id = server.id
            fact.source_key = server.id
        fact.updated_at = now() - timedelta(days=5)
        job = m.Job(kind="ipam_address_scan", target_id=rid, status="running")
        db.add(job)
        db.commit()
        sources = sql_sources.SQLContext(db, vlan, job.id, point=True).for_row(row)
        before = now()
    calls = []

    async def dns(address, server):
        calls.append(address)
        assert (server.address if server else None) == ("192.0.2.53" if configured else None)
        return name

    monkeypatch.setattr(adapters, "reverse_dns", dns)
    result = await sources.resolve()
    assert calls == [row.address]
    assert result["values"]["hostname"] == name
    assert not any(i["code"] == "stale_source" for i in result["issues"])
    with sf() as db:
        pipeline.save_result(db, db.get(m.IPAddress, rid), before, result)
        db.commit()
        fact = db.scalar(select(m.DNSRecord).where(m.DNSRecord.address_id == rid))
        assert fact.hostname == name
        assert fact.updated_at >= before
        value = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).values
        assert value["hostname"] == name


@pytest.mark.parametrize("condition", ["valid", "stale", "multi_mac", "shared_fid", "uplink", "two_ports"])
def test_partial_table_keeps_valid_mac_port_without_endpoint_neighbor(network, condition):
    sf, vid, rid, ids = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        # One unrelated row could not resolve its bridge port. The target row is valid.
        evidence = read(state)
        evidence["tables"]["vlan_fdb_port"]["700.0.17.34.51.68.102"] = "999"
        evidence["tables"]["vlan_fdb_status"]["700.0.17.34.51.68.102"] = "3"
        evidence.pop("_canonical_fdb_times", None)
        state.evidence = evidence
        db.flush()
        state.fdb_at = now() - timedelta(days=2)
        assert any(r.name == "vlan_fdb_port" and r.status == "incomplete" for r in state.unsupported)
        entry = next(e for e in state.mac_entries if e.mac_address == MAC)
        if condition == "stale":
            entry.observed_at = now() - timedelta(days=2)
        elif condition == "multi_mac":
            state.mac_entries.append(
                m.SwitchMacEntry(
                    vrf_id=row.vrf_id,
                    vlan_vid=20,
                    fdb_id=700,
                    mac_address="00:11:22:33:44:77",
                    port=entry.port,
                    bridge_port=9,
                    if_index=101,
                    status="3",
                )
            )
        elif condition == "two_ports":
            state.ports.append(m.SourcePort(if_index=102, name="Gi1/0/2", oper_status="up"))
            state.mac_entries.append(
                m.SwitchMacEntry(
                    vrf_id=row.vrf_id,
                    vlan_vid=20,
                    fdb_id=700,
                    mac_address=MAC,
                    port="Gi1/0/2",
                    bridge_port=10,
                    if_index=102,
                    status="3",
                )
            )
        elif condition == "shared_fid":
            state.vlan_fdbs.append(m.SourceVLANFDB(vlan_vid=21, fdb_id=700))
        elif condition == "uplink":
            db.add(
                m.Link(
                    device_id=ids[1],
                    interface_name=entry.port,
                    remote_device_id=ids[2],
                    remote_name="Core",
                    remote_port="Gi1/0/1",
                    source="lldp",
                    last_seen_at=now(),
                )
            )
        db.commit()
    with sf() as db:
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        proof = attachment(db, row, vlan, MAC, evidence=point_evidence(db, row, vlan, MAC))
        if condition == "valid":
            assert (proof["connected_device"], proof["connected_port"]) == ("Access", "Gi1/0/1")
            assert proof["connections"][0]["source"] == "gateway+vlan_fdb"
            assert not proof["connections"][0].get("remote_port")
        else:
            assert not proof["connections"]
