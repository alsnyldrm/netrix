"""IPAM reads never collect evidence; only scheduled full scans and ICMP timers run."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import scheduler, services, worker
from netrix.core import now
from netrix.ipam import adapters, jobs, scan_schedules
from sqlalchemy import func, select
from test_ipam_workspace import integration, prefix


def test_create_and_repeated_reads_never_enqueue_sources(admin_client, inventory, env, monkeypatch):
    vlan = prefix(admin_client, inventory)
    row = admin_client.post(
        "/api/v1/addresses", json={"address": "192.0.2.1", "vrf_id": vlan["vrf_id"], "vlan_id": vlan["id"]}
    ).json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Read requests must not access DNS, VMware, DHCP or devices")

    for name in ("ping", "reverse_dns", "vcenter_records", "windows_dhcp"):
        monkeypatch.setattr(adapters, name, forbidden)
    for _ in range(3):
        assert admin_client.get("/api/v1/vlans").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/addresses/{row['id']}").status_code == 200
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind.in_(jobs.KINDS))) == 0


def test_manual_collectors_are_rejected(admin_client, inventory, env):
    vlan = prefix(admin_client, inventory)
    config = integration(admin_client, vlan)
    for path in (
        f"/ipam/vlans/{vlan['id']}/discover",
        f"/ipam/vlans/{vlan['id']}/ping",
        f"/integrations/{config['id']}/sync",
    ):
        response = admin_client.post("/api/v1" + path)
        assert response.status_code == 409, response.text
    with env() as db:
        for kind, target in (
            ("ipam_discover", vlan["id"]),
            ("ipam_ping", vlan["id"]),
            ("integration", config["id"]),
        ):
            with pytest.raises(HTTPException) as error:
                services.enqueue(db, kind, target)
            assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_ping_is_icmp_only_and_recovery_updates_cached_status(
    admin_client, inventory, env, monkeypatch
):
    from netrix.ipam import read_cache

    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    vlan = prefix(admin_client, inventory)
    with env() as db:
        source = db.get(m.VLAN, vlan["id"])
        row = jobs.observe(db, source, "192.0.2.1", "dns", "system", {"hostname": "stored.example.test"})
        jobs.observe(db, source, row.address, "icmp", source.id, {"reachability": "no_reply"})
        db.commit()
        row_id = row.id

    def forbidden(*args, **kwargs):
        raise AssertionError("ICMP timer attempted a full-scan source read")

    for name in ("reverse_dns", "vcenter_records", "windows_dhcp"):
        monkeypatch.setattr(adapters, name, forbidden)
    import netrix.ipam.network as network

    monkeypatch.setattr(network, "refresh", forbidden)

    async def ping(address):
        assert address == "192.0.2.1"
        return True

    monkeypatch.setattr(adapters, "ping", ping)
    url = f"/api/v1/ipam/vlans/{vlan['id']}/addresses?active_only=true"
    assert not admin_client.get(url).json()["items"]
    events = []
    monkeypatch.setattr(services.redis_client(), "publish", lambda *args: events.append(args))
    with env() as db:
        job = services.enqueue(db, "ipam_ping", vlan["id"], ipam_origin="ping_timer")
        id = job.id
    assert worker.claim(interactive=False, include_kinds=("ipam_ping",)) == id
    await worker.execute(id)
    import json

    assert events and all(
        json.loads(message) == {"type": "ipam_ping", "vlan_id": vlan["id"]}
        for channel, message in events
        if channel == "netrix:events"
    )
    row = admin_client.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert row["availability"] == "active" and row["hostname"] == "stored.example.test"
    assert admin_client.get(url).json()["items"][0]["id"] == row_id
    with env() as db:
        assert db.get(m.Job, id).status == "succeeded"
        assert (
            db.scalar(
                select(func.count()).select_from(m.IPObservation).where(m.IPObservation.source == "dns")
            )
            == 1
        )


def test_only_groups_dispatch_full_scans_and_ping_deadlines_are_independent(admin_client, inventory, env):
    vlan = prefix(admin_client, inventory)
    config = integration(admin_client, vlan)
    at = now()
    with env() as db:
        row = db.get(m.VLAN, vlan["id"])
        row.ping_enabled, row.ping_interval, row.last_ping_at = True, 30, at
        row.discovery_enabled = True  # Old persisted switch must no longer schedule full scans.
        db.get(m.Integration, config["id"]).interval_seconds = 60
        db.commit()
    scheduler.tick()
    with env() as db:
        assert not db.scalar(select(m.Job).where(m.Job.kind.in_(("ipam_discover", "integration"))))
    scheduler.dispatch_pings(at + timedelta(seconds=29))
    with env() as db:
        assert not db.scalar(select(m.Job).where(m.Job.kind == "ipam_ping"))
    scheduler.dispatch_pings(at + timedelta(seconds=30))
    scheduler.dispatch_pings(at + timedelta(seconds=31))
    with env() as db:
        rows = db.scalars(select(m.Job).where(m.Job.kind == "ipam_ping")).all()
        assert len(rows) == 1 and rows[0].result["ipam_origin"] == "ping_timer"


@pytest.mark.asyncio
async def test_old_unattributed_scan_is_cancelled_before_network(admin_client, inventory, env, monkeypatch):
    vlan = prefix(admin_client, inventory)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unscheduled scan reached the network")

    monkeypatch.setattr(adapters, "ping", forbidden)
    with env() as db:
        job = m.Job(kind="ipam_discover", target_id=vlan["id"], active_key="legacy:" + vlan["id"])
        db.add(job)
        db.commit()
        id = job.id
    await worker.execute(id)
    with env() as db:
        job = db.get(m.Job, id)
        assert job.status == "cancelled" and job.active_key is None


def test_ping_lane_can_claim_while_same_vlan_has_a_full_scan(admin_client, inventory, env):
    vlan = prefix(admin_client, inventory)
    with env() as db:
        full = services.enqueue(db, "ipam_discover", vlan["id"], ipam_origin="schedule")
        full.status = "running"
        full.heartbeat_at = now()
        ping = services.enqueue(db, "ipam_ping", vlan["id"], ipam_origin="ping_timer")
        ping_id = ping.id
        db.commit()
    assert worker.claim(interactive=False, include_kinds=("ipam_ping",)) == ping_id


def test_group_dispatch_still_creates_scheduled_full_scan(admin_client, inventory, env):
    vlan = prefix(admin_client, inventory)
    data = dict(
        name="Full scan",
        vlan_ids=[vlan["id"]],
        frequency="daily",
        start_at=(now() - timedelta(seconds=1)).isoformat(),
    )
    response = admin_client.post("/api/v1/ipam/scan-groups", json=data)
    assert response.status_code == 201
    scan_schedules.dispatch_due()
    with env() as db:
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover"))
        assert job and job.result["ipam_origin"] == "schedule"


def test_short_ping_interval_is_saved_without_activating_sources(admin_client, inventory):
    vlan = prefix(admin_client, inventory)
    result = admin_client.put(f"/api/v1/ipam/vlans/{vlan['id']}/settings", json={"ping_interval": 10})
    assert result.status_code == 200 and result.json()["ping_interval"] == 10
    data = {k: vlan[k] for k in ("name", "vid", "cidr", "vrf_id")}
    data["description"] = "Metadata edit"
    result = admin_client.put(f"/api/v1/vlans/{vlan['id']}", json=data)
    assert result.status_code == 200 and result.json()["ping_interval"] == 10
    assert (
        admin_client.put(
            f"/api/v1/ipam/vlans/{vlan['id']}/settings", json={"discovery_enabled": True}
        ).status_code
        == 422
    )


def test_ping_notification_is_forwarded_without_collecting(admin_client, inventory, monkeypatch):
    import json
    from types import SimpleNamespace

    from netrix import main

    vlan = prefix(admin_client, inventory)

    class Subscription:
        def subscribe(self, *args):
            pass

        def close(self):
            pass

        def get_message(self, **kwargs):
            return {"data": json.dumps({"type": "ipam_ping", "vlan_id": vlan["id"]})}

    monkeypatch.setattr(main, "redis_client", lambda: SimpleNamespace(pubsub=Subscription))
    with admin_client.websocket_connect("/api/v1/ws", headers={"origin": "http://testserver"}) as socket:
        assert socket.receive_json() == {"type": "ipam_ping", "vlan_id": vlan["id"]}
