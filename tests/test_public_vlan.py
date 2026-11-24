import pytest
from netrix import models as m
from netrix.ipam import adapters, service, table
from sqlalchemy import select
from test_ipam_source_contract import network as network


def test_public_includes_registered_no_reply_and_avoids_topology(network, monkeypatch):
    sf, vid, rid, _ = network
    from netrix.ipam import connections

    monkeypatch.setattr(connections, "Evidence", lambda *_a, **_k: pytest.fail("Public read loaded topology"))
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.network_type = "public"
        row = db.get(m.IPAddress, rid)
        row.hostname = "manual.example"
        service.observe(db, vlan, row.address, "icmp", vlan.id, {"reachability": "no_reply"})
        db.commit()
        result = table.addresses(db, vlan, active_only=True)
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["availability"] == "active"
        assert item["ping"] == "passive"
        assert item["sources"] == ["icmp"]
        assert item["hostname"] == "manual.example"
        assert result["vlan"]["used"] == 1
        assert "scan_status" not in {c["key"] for c in result["columns"]}
        assert "ping" in {c["key"] for c in result["columns"]}
        assert len(table.addresses(db, vlan, q=row.address, active_only=True)["items"]) == 1


@pytest.mark.parametrize("kind", ["ipam_discover", "ipam_address_scan"])
async def test_public_scan_only_calls_ping(network, monkeypatch, kind):
    sf, vid, rid, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.network_type = "public"
        vlan.cidr = "192.0.2.8/30"
        job = m.Job(
            kind=kind,
            target_id=rid if kind == "ipam_address_scan" else vid,
            status="running",
            result={"ipam_origin": "manual"},
        )
        if kind == "ipam_address_scan":
            row = db.get(m.IPAddress, rid)
            job.result = {**job.result, "address_scope": [row.address, row.vrf_id, row.vlan_id]}
        db.add(job)
        db.commit()
        jid = job.id

    calls = []

    async def ping(address):
        calls.append(address)
        return address == "192.0.2.9"

    async def forbidden(*_a, **_k):
        pytest.fail("Public queried a non-ping source")

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", forbidden)
    from netrix.ipam.jobs import execute

    await execute(jid, kind, object())
    assert calls == (["192.0.2.10"] if kind == "ipam_address_scan" else ["192.0.2.9", "192.0.2.10"])
    with sf() as db:
        if kind == "ipam_discover":
            assert db.scalar(select(m.IPAddress).where(m.IPAddress.address == "192.0.2.9"))
        assert db.get(m.IPAddress, rid).status == "active"


def test_public_manual_creation_defaults_to_active(admin_client, network):
    sf, vid, _, _ = network
    with sf() as db:
        v = db.get(m.VLAN, vid)
        v.network_type = "public"
        vrf = v.vrf_id
        db.commit()
    response = admin_client.post("/api/v1/addresses", json={
        "address": "192.0.2.22", "vlan_id": vid, "vrf_id": vrf,
    })
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"
