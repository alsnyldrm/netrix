"""Manual IP/VLAN jobs reconcile SQL without touching any external source."""

from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.ipam import adapters, service, sql_sources
from netrix.sources import records
from sqlalchemy import select
from test_ipam_source_contract import network as network


class NoNetwork:
    def __getattr__(self, name):
        raise AssertionError("Manual job attempted protocol operation: " + name)


@pytest.fixture
def blocked(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("Manual job attempted network operation")

    for name in (
        "ping",
        "reverse_dns",
        "windows_dhcp",
        "windows_dhcp_point",
        "vcenter_records",
        "vcenter_point",
    ):
        if hasattr(adapters, name):
            monkeypatch.setattr(adapters, name, forbidden)
    # Guard low-level UDP too: connect-only guards miss SNMP datagrams.
    import socket

    monkeypatch.setattr(socket.socket, "sendto", forbidden)
    monkeypatch.setattr(socket.socket, "sendmsg", forbidden)


def source_snapshot(db):
    return {
        cls.__tablename__: sorted(
            [tuple(str(getattr(r, c.name)) for c in cls.__table__.columns) for r in db.scalars(select(cls))]
        )
        for cls in (
            m.GatewayBinding,
            m.DNSRecord,
            m.DHCPBinding,
            m.PingState,
            m.SwitchMacEntry,
            m.IPAMNetworkState,
            m.VMwareVM,
            m.VMwareNIC,
            m.VMwareAddress,
        )
    }


@pytest.mark.parametrize("kind", ["address", "vlan"])
async def test_manual_jobs_use_sql_and_preserve_all_sources(admin_client, network, blocked, kind):
    sf, vid, rid, ids = network
    with sf() as db:
        d = db.get(m.Device, ids[0])
        d.is_gateway = True
        other = service.observe(
            db, db.get(m.VLAN, vid), "192.0.2.11", "dns", "system", {"hostname": "other.example"}
        )
        db.commit()
        other_id = other.id
        before = source_snapshot(db)
        other_before = deepcopy(service.enrich(db, [other])[0])
    path = f"/api/v1/ipam/addresses/{rid}/scan" if kind == "address" else f"/api/v1/ipam/vlans/{vid}/discover"
    job = admin_client.post(path).json()
    assert worker.claim(interactive=False, include_kinds=(job["kind"],)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        j = db.get(m.Job, job["id"])
        assert j.status in ("succeeded", "partial"), j.error
        assert j.progress == (1 if kind == "address" else 2)
        assert source_snapshot(db) == before
        result = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid))
        assert result.values["hostname"] == "dns.example"
        assert result.values["mac_address"] == "00:11:22:33:44:55"
        if kind == "address":
            assert service.enrich(db, [db.get(m.IPAddress, other_id)])[0] == other_before
        assert db.get(m.VLAN, vid).last_discovery_at is None


async def test_sql_vm_and_dhcp_bind_existing_facts_without_rewriting_them(admin_client, network, blocked):
    sf, vid, rid, ids = network
    with sf() as db:
        config = m.Integration(
            name="SQL VM",
            kind="vcenter",
            port=443,
            host="192.0.2.200",
            encrypted_secret="unused",
            enabled=True,
        )
        db.add(config)
        db.flush()
        records.vmware(
            db,
            config.id,
            dict(
                vm_id="vm-1",
                nic_key="4000",
                address="192.0.2.10",
                mac_address="00:11:22:33:44:55",
                hostname="sql-vm",
                operating_system="Linux",
                dvswitch="ds",
                dvswitch_name="FBU-DS",
                network="VLAN-020",
                dvport="89",
            ),
            at=now() - timedelta(hours=1),
        )
        db.commit()
        before = source_snapshot(db)
    job = admin_client.post(f"/api/v1/ipam/addresses/{rid}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "succeeded", db.get(m.Job, job["id"]).error
        result = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid))
        assert (
            result.values["hostname"],
            result.values["connected_device"],
            result.values["connected_port"],
        ) == ("sql-vm", "FBU-DS", "89")
        assert source_snapshot(db) == before


async def test_sql_teaming_uses_stored_dns_and_both_ports(admin_client, network, blocked):
    sf, vid, rid, ids = network
    with sf() as db:
        db.get(m.IPAddress, rid).nic_teaming = True
        for port in ("A7", "B7"):
            db.add(
                m.Link(
                    device_id=ids[1],
                    interface_name=port,
                    remote_name="dns.example",
                    remote_port=port,
                    source="lldp",
                    last_seen_at=now(),
                    is_current=True,
                )
            )
        db.commit()
    job = admin_client.post(f"/api/v1/ipam/addresses/{rid}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "succeeded", db.get(m.Job, job["id"]).error
        value = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).values
        assert {c["port"] for c in value["connections"]} == {"A7", "B7"}


async def test_cancel_and_scope_change_prevent_sql_result_write(admin_client, network, blocked, monkeypatch):
    sf, vid, rid, ids = network
    original = sql_sources.SQLSources.resolve

    async def moved(self, *a, **k):
        value = await original(self, *a, **k)
        with sf() as db:
            db.get(m.IPAddress, rid).address = "192.0.2.90"
            db.commit()
        return value

    monkeypatch.setattr(sql_sources.SQLSources, "resolve", moved)
    job = admin_client.post(f"/api/v1/ipam/addresses/{rid}/scan").json()
    assert worker.claim(interactive=False, include_kinds=("ipam_address_scan",)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "cancelled"
        assert not db.scalar(select(m.IPAMResult.id))


async def test_sql_vlan_import_is_scoped_and_commits_each_result(admin_client, network, blocked, monkeypatch):
    sf, vid, rid, ids = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        for address in ("192.0.2.12", "192.0.2.13", "192.0.2.0", "192.0.2.255", "198.51.100.80"):
            from types import SimpleNamespace

            records.gateway(
                db,
                SimpleNamespace(address=address, vrf_id=vlan.vrf_id),
                {"device_id": ids[0], "mac_address": "00:11:22:33:44:55"},
                now(),
            )
        db.commit()
        before = source_snapshot(db)
    visible = []

    def published(**kwargs):
        with sf() as db:
            visible.append(len(list(db.scalars(select(m.IPAMResult.id)))))

    monkeypatch.setattr(sql_sources, "publish", published)
    job = admin_client.post(f"/api/v1/ipam/vlans/{vid}/discover").json()
    assert worker.claim(interactive=False, include_kinds=(job["kind"],)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        assert db.get(m.Job, job["id"]).status in ("succeeded", "partial")
        assert set(db.scalars(select(m.IPAddress.address).where(m.IPAddress.vlan_id == vid))) == {
            "192.0.2.10",
            "192.0.2.12",
            "192.0.2.13",
        }
        assert source_snapshot(db) == before
    assert visible == [1, 2, 3]


async def test_sql_failure_keeps_verified_previous_resolution(admin_client, network, blocked):
    from netrix.ipam import pipeline

    sf, vid, rid, ids = network
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        pipeline.save_result(
            db,
            row,
            now(),
            {
                "status": "success",
                "issues": [],
                "steps": [],
                "values": {
                    "hostname": "verified.example",
                    "mac_address": "00:11:22:33:44:55",
                    "connected_device": "Access",
                    "connected_port": "Gi1/0/1",
                    "connection_type": "physical",
                    "connections": [
                        {
                            "device_id": ids[1],
                            "device_name": "Access",
                            "port": "Gi1/0/1",
                            "source": "switch_fdb",
                            "confidence": 0.9,
                        }
                    ],
                },
            },
        )
        db.commit()
        previous = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).values
        for state in db.scalars(select(m.IPAMNetworkState)):
            state.healthy = False
        for fact in db.scalars(select(m.GatewayBinding)):
            fact.present = False
        db.commit()
    job = admin_client.post(f"/api/v1/ipam/addresses/{rid}/scan").json()
    assert worker.claim(interactive=False, include_kinds=(job["kind"],)) == job["id"]
    await worker.execute(job["id"], NoNetwork())
    with sf() as db:
        result = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid))
        assert result.status == "problem"
        assert result.values["connected_port"] == previous["connected_port"]
        assert result.values["mac_address"] == previous["mac_address"]
