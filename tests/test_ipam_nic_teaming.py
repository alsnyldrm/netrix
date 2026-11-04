"""NIC-Teaming resolves DNS against SQL only and preserves every physical NIC."""

from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import adapters, pipeline, service, teaming
from sqlalchemy import func, select
from test_ipam_source_contract import network as network


def seed(network):
    sf, vid, rid, devices = network
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        row.nic_teaming = True
        for device, ports in ((devices[1], ("A3", "B3")), (devices[2], ("1", "2", "3", "4"))):
            for index, port in enumerate(ports):
                db.add(
                    m.Link(
                        device_id=device,
                        interface_name=port,
                        remote_name="SV-VW-01.fbu.edu.tr",
                        remote_port=f"vmnic{index}",
                        source="lldp",
                        last_seen_at=now(),
                        evidence={"lldp": {"system_name": "SV-VW-01.fbu.edu.tr"}},
                    )
                )
        db.commit()
    return sf, vid, rid, devices


async def test_only_dns_then_sql_all_switches_and_nics(network, monkeypatch):
    sf, vid, rid, _ = seed(network)
    calls = []

    async def dns(address, server):
        calls.append(address)
        return "sv-vw-01.fbu.edu.tr."

    monkeypatch.setattr(adapters, "reverse_dns", dns)
    # Construction of ordinary source readers itself is forbidden in this mode.
    from netrix.ipam import point_sources

    monkeypatch.setattr(
        point_sources.PointSources,
        "__init__",
        lambda *a, **k: pytest.fail("external source reader constructed"),
    )
    with sf() as db:
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        sources = pipeline.sources_for(db, row, vlan, object())
    resolved = await pipeline.resolve(row.address, sources)
    assert calls == [row.address]
    assert resolved["status"] == "success"
    assert {(c["device_name"], c["port"]) for c in resolved["values"]["connections"]} == {
        ("Access", "A3"),
        ("Access", "B3"),
        ("Core", "1"),
        ("Core", "2"),
        ("Core", "3"),
        ("Core", "4"),
    }
    assert {s["source"] for s in resolved["steps"] if s["status"] == "skipped_nic_teaming"} == {
        "gateway",
        "vmware",
        "backbone",
        "switch",
        "dhcp",
    }
    with sf() as db:
        assert pipeline.save_result(db, db.get(m.IPAddress, rid), now(), resolved)
        result = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid))
        db.commit()
        assert len(result.connection_rows) == 6
        assert all(
            c.neighbor_id and not c.mac_port_id and not c.vmware_nic_id for c in result.connection_rows
        )
    with sf() as db:
        detail = service.enrich(db, [db.get(m.IPAddress, rid)])[0]
        assert detail["nic_teaming"] is True
        assert len(detail["connections"]) == 6
        assert detail["hostname"] == "sv-vw-01.fbu.edu.tr."
        assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1


@pytest.mark.parametrize("change", ["excluded", "inactive", "other_vrf", "similar_name", "stale"])
def test_neighbor_identity_and_scope(network, change):
    sf, _, rid, devices = seed(network)
    with sf() as db:
        links = list(
            db.scalars(
                select(m.Link).where(
                    m.Link.device_id == devices[1], m.Link.remote_name == "SV-VW-01.fbu.edu.tr"
                )
            )
        )
        for link in links:
            if change == "excluded":
                link.auto_add_excluded = True
            if change == "inactive":
                link.is_current = False
            if change == "similar_name":
                link.remote_name = "SV-VW-01.other.edu.tr"
                link.evidence = {"lldp": {"system_name": "SV-VW-01.other.edu.tr"}}
            if change == "stale":
                link.last_seen_at = now() - timedelta(days=2)
        if change == "other_vrf":
            vrf = m.VRF(name="Different VRF")
            db.add(vrf)
            db.flush()
            db.get(m.Device, devices[1]).vrf_id = vrf.id
        db.commit()
        conns = teaming.neighbors(db, db.get(m.IPAddress, rid), "sv-vw-01.fbu.edu.tr")
        resolved = teaming.result("sv-vw-01.fbu.edu.tr", conns)
        if change == "stale":
            assert len(conns) == 6
            assert resolved["status"] == "problem" and any(
                i["code"] == "stale_source" for i in resolved["issues"]
            )
        else:
            assert len(conns) == 4


async def test_missing_dns_never_guesses_saved_or_manual_hostname(network, monkeypatch):
    sf, vid, rid, _ = seed(network)

    async def missing(*_):
        return ""

    monkeypatch.setattr(adapters, "reverse_dns", missing)
    with sf() as db:
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        row.hostname = "SV-VW-01.fbu.edu.tr"
        db.commit()
    result = await teaming.TeamingSources(row, vlan).resolve()
    assert result["status"] == "problem"
    assert result["values"]["connections"] == []
    assert result["issues"][0]["code"] == "missing_hostname"


def test_editing_and_page_reads_use_only_existing_sql(admin_client, network):
    sf, vid, rid, _ = seed(network)
    response = admin_client.put(
        f"/api/v1/addresses/{rid}",
        json={
            "address": "192.0.2.10",
            "vlan_id": vid,
            "vrf_id": admin_client.get(f"/api/v1/addresses/{rid}").json()["vrf_id"],
            "nic_teaming": True,
        },
    )
    assert response.status_code == 200, response.text
    detail = admin_client.get(f"/api/v1/ipam/addresses/{rid}")
    assert detail.status_code == 200 and detail.json()["nic_teaming"]
    with sf() as db:
        assert not db.scalar(select(m.Job).where(m.Job.status.in_(("queued", "running"))))
