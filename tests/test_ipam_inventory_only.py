"""IPAM never opens switch sessions; inventory owns MAC/port and neighbor facts."""

from copy import deepcopy

import pytest
from netrix import models as m
from netrix import worker
from netrix.ipam import adapters, point_sources, service
from netrix.ipam.bulk_sources import BulkContext
from netrix.sources.network import read
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ipam_source_contract import network as network


class NoSwitch:
    def __getattr__(self, name):
        raise AssertionError("IPAM attempted switch access: " + name)


def inventory_facts(db, ids):
    # Compare committed SQL, not the identity map bypassed by bulk inventory upserts.
    facts = {}
    with Session(db.get_bind()) as reader:
        for d in ids:
            state = reader.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == d))
            facts[d] = {
                "payload": deepcopy(read(state)),
                "mac_rows": sorted(
                    [
                        tuple(str(getattr(e, col.name)) for col in m.SwitchMacEntry.__table__.columns)
                        for e in state.mac_entries
                    ]
                ),
            }
    return facts


@pytest.mark.parametrize("available", [True, False])
async def test_scheduled_scan_reads_switch_sql_without_touching_or_refreshing_it(
    admin_client, network, monkeypatch, available
):
    sf, vid, rid, ids = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.cidr = "192.0.2.8/30"
        # A switch marked as a gateway must still never be contacted by IPAM.
        db.get(m.Device, ids[2]).is_gateway = True
        if not available:
            state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
            state.mac_entries = []
        core = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[2]))
        core.mac_entries.append(
            m.SwitchMacEntry(
                vrf_id=vlan.vrf_id,
                vlan_vid=20,
                fdb_id=900,
                mac_address="00:11:22:33:44:99",
                port="old-port",
                if_index=199,
                bridge_port=99,
                status="3",
                present=False,
            )
        )
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "schedule"})
        db.add(job)
        db.commit()
        jid = job.id
        before = inventory_facts(db, ids[1:])
        gateway = deepcopy(
            read(db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[0])))
        )
    calls = []

    class Collector:
        async def ipam(self, host, *_):
            assert host == "198.51.100.1", "IPAM contacted an inventory switch"
            calls.append(host)
            return deepcopy(gateway)

        async def ipam_switch(self, *_):
            raise AssertionError("IPAM attempted direct switch MAC lookup")

    async def forbidden(*a, **kw):
        raise AssertionError("IPAM attempted switch SSH lookup")

    async def ping(address):
        return address == "192.0.2.10"

    async def dns(*_):
        return "dns.example"

    from netrix.discovery import protocols

    monkeypatch.setattr(protocols, "fetch_neighbor_detail", forbidden)
    monkeypatch.setattr(protocols, "fetch_neighbor_ports", forbidden)
    if hasattr(point_sources, "fetch_neighbor_ports"):
        monkeypatch.setattr(point_sources, "fetch_neighbor_ports", forbidden)
    import netrix.ipam.bulk_sources as bulk

    if hasattr(bulk, "fetch_neighbor_detail"):
        monkeypatch.setattr(bulk, "fetch_neighbor_detail", forbidden)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    await worker.execute(jid, Collector())
    with sf() as db:
        job = db.get(m.Job, jid)
        assert job.status == ("succeeded" if available else "partial"), job.error
        assert calls == ["198.51.100.1"]
        assert job.result["network"]["switch_mode"] == "inventory_sql"
        after = inventory_facts(db, ids[1:])
        for did in ids[1:]:
            for key in before[did]["payload"]:
                assert after[did]["payload"][key] == before[did]["payload"][key], (
                    key,
                    after[did]["payload"][key],
                    before[did]["payload"][key],
                )
            assert after[did]["mac_rows"] == before[did]["mac_rows"]
        row = service.enrich(db, [db.get(m.IPAddress, rid)])[0]
        if available:
            assert (row["connected_device"], row["connected_port"]) == ("Access", "Gi1/0/1")
        else:
            assert not row["connected_device"]
            assert any(i["code"] == "attachment_missing" for i in row["scan_result"]["issues"])


async def test_switch_source_and_point_fallback_are_read_only_even_if_no_match(network):
    sf, vid, rid, ids = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "schedule"})
        db.add(job)
        db.commit()
        context = BulkContext(db, db.get(m.VLAN, vid), NoSwitch(), job.id)
        row = db.get(m.IPAddress, rid)
        before = inventory_facts(db, ids)
    await context.network("switch")
    assert context.read_counts["switch"] == 0
    point = context.base
    point.row = row
    for mac in ("00:11:22:33:44:55", "00:11:22:33:44:aa"):
        await point.physical(row.address, mac)
    with sf() as db:
        assert inventory_facts(db, ids) == before


@pytest.mark.parametrize("point", [False, True])
async def test_two_switch_nics_are_resolved_from_stored_neighbors_without_device_access(network, point):
    from netrix.core import now
    from netrix.ipam import sql_sources

    sf, vid, rid, ids = network
    with sf() as db:
        for did, port, nic in ((ids[1], "A7", "00:11:22:aa:00:01"), (ids[2], "B7", "00:11:22:aa:00:02")):
            obs = db.scalar(select(m.Observation).where(m.Observation.device_id == did))
            obs.evidence = {
                **obs.evidence,
                "neighbors": [
                    {
                        "interface_name": port,
                        "remote_name": "physical-host",
                        "remote_port": nic,
                        "source": "lldp+cdp",
                        "evidence": {
                            "lldp": {
                                "chassis_subtype": 4,
                                "chassis_id": "00:11:22:33:44:55",
                                "port_subtype": 3,
                                "port_id": nic,
                                "transport": "ssh_detail",
                            },
                            "cdp": {
                                "device_id": "00:11:22:33:44:55",
                                "management_address": "192.0.2.10",
                                "port_id": nic,
                                "transport": "ssh_detail",
                            },
                        },
                    }
                ],
            }
        job = m.Job(kind="ipam_address_scan", target_id=rid, status="running")
        db.add(job)
        db.commit()
        row = db.get(m.IPAddress, rid)
        context = sql_sources.SQLContext(db, db.get(m.VLAN, vid), job.id, point=point)
        before = inventory_facts(db, ids[1:])
    result = await context.for_row(row).resolve()
    assert {(c["device_id"], c["port"]) for c in result["values"]["connections"]} == {
        (ids[1], "A7"),
        (ids[2], "B7"),
    }
    from netrix.ipam import pipeline

    with sf() as db:
        pipeline.save_result(db, db.get(m.IPAddress, rid), now(), result)
        db.commit()
        output = service.enrich(db, [db.get(m.IPAddress, rid)])[0]
        assert {(c["device_id"], c["port"]) for c in output["connections"]} == {
            (ids[1], "A7"),
            (ids[2], "B7"),
        }
        after = inventory_facts(db, ids[1:])
        for did in ids[1:]:
            for key in before[did]["payload"]:
                assert after[did]["payload"][key] == before[did]["payload"][key], (
                    key,
                    after[did]["payload"][key],
                    before[did]["payload"][key],
                )
            assert after[did]["mac_rows"] == before[did]["mac_rows"]
