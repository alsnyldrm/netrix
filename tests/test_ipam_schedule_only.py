"""IPAM reads never collect evidence; explicit user actions, schedules and ICMP timers are separate."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import scheduler, services, worker
from netrix.core import now
from netrix.ipam import adapters, jobs, scan_schedules
from sqlalchemy import func, select
from test_ipam_workspace import integration, prefix


def test_repeated_reads_do_not_add_jobs(admin_client, inventory, env, monkeypatch):
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


@pytest.mark.parametrize("status", ["queued", "running", "partial"])
@pytest.mark.parametrize("origin", ["manual", "schedule", "vlan_create"])
def test_refresh_restores_same_scan_without_requeue(
    admin_client, inventory, env, monkeypatch, status, origin
):
    vlan = prefix(admin_client, inventory)
    from test_ipam_workspace import timer_job

    id = timer_job("ipam_discover", vlan["id"])["id"]
    with env() as db:
        job = db.get(m.Job, id)
        job.status = status
        job.result = {"ipam_origin": origin, "scan_phase": "addresses"}
        job.progress, job.total = 50, 254
        if status == "partial":
            job.active_key = None
        db.commit()
        created = job.created_at
        count = db.scalar(select(func.count()).select_from(m.Job))

    def forbidden(*args, **kwargs):
        raise AssertionError("Refreshing a scan must neither enqueue nor collect sources")

    monkeypatch.setattr(services, "enqueue", forbidden)
    for name in ("ping", "reverse_dns", "vcenter_records", "windows_dhcp"):
        monkeypatch.setattr(adapters, name, forbidden)
    for _ in range(3):
        assert admin_client.get("/api/v1/vlans").status_code == 200
        assert admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses").status_code == 200
        restored = admin_client.get(f"/api/v1/ipam/vlans/{vlan['id']}/scan").json()
        assert (restored["id"], restored["status"], restored["progress"], restored["total"]) == (
            id,
            status,
            50,
            254,
        )
        assert restored["result"]["ipam_origin"] == origin
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == count
        assert db.get(m.Job, id).created_at == created


@pytest.mark.parametrize("role", ["super_admin", "admin", "operator"])
def test_manual_vlan_actions_are_queued_once_but_independent_sync_is_blocked(
    admin_client, inventory, env, role
):
    vlan = prefix(admin_client, inventory)
    config = integration(admin_client, vlan)
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    for action in ("discover", "ping"):
        url = f"/api/v1/ipam/vlans/{vlan['id']}/{action}"
        response = admin_client.post(url)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["kind"] == "ipam_" + action and job["status"] == "queued"
        assert job["requested_by"] and job["result"]["ipam_origin"] == "manual"
        assert admin_client.post(url).json()["id"] == job["id"]
        with env() as db:
            scheduled = services.enqueue(
                db,
                "ipam_" + action,
                vlan["id"],
                ipam_origin="schedule" if action == "discover" else "ping_timer",
            )
            assert scheduled.id == job["id"]
    assert admin_client.post(f"/api/v1/integrations/{config['id']}/sync").status_code == (
        403 if role == "operator" else 409
    )
    with env() as db:
        for kind, target in (
            ("ipam_discover", vlan["id"]),
            ("ipam_ping", vlan["id"]),
            ("integration", config["id"]),
        ):
            for origin in (None, "manual"):
                with pytest.raises(HTTPException) as error:
                    services.enqueue(db, kind, target, ipam_origin=origin)
                assert error.value.status_code == 409


def test_viewer_cannot_start_manual_vlan_actions(admin_client, inventory, env):
    vlan = prefix(admin_client, inventory)
    with env() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    for action in ("discover", "ping"):
        assert admin_client.post(f"/api/v1/ipam/vlans/{vlan['id']}/{action}").status_code == 403
    with env() as db:
        assert list(db.scalars(select(m.Job.id))) == []


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.asyncio
async def test_ping_is_icmp_only_and_recovery_updates_cached_status(
    admin_client, inventory, env, monkeypatch, manual
):

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
    if manual:
        response = admin_client.post(f"/api/v1/ipam/vlans/{vlan['id']}/ping")
        assert response.status_code == 202, response.text
        id = response.json()["id"]
    else:
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
    assert all(item["id"] != id for item in admin_client.get("/api/v1/jobs").json()["items"])


def test_legacy_full_scan_timers_stay_off_and_ping_deadlines_are_independent(admin_client, inventory, env):
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
        assert (
            list(db.scalars(select(m.Job.id).where(m.Job.kind.in_(("ipam_discover", "integration"))))) == []
        )
    scheduler.dispatch_pings(at + timedelta(seconds=29))
    with env() as db:
        assert not db.scalar(select(m.Job).where(m.Job.kind == "ipam_ping"))
    scheduler.dispatch_pings(at + timedelta(seconds=30))
    scheduler.dispatch_pings(at + timedelta(seconds=31))
    with env() as db:
        rows = db.scalars(select(m.Job).where(m.Job.kind == "ipam_ping")).all()
        assert len(rows) == 1 and rows[0].result["ipam_origin"] == "ping_timer"


@pytest.mark.parametrize("origin", [None, "manual", "vlan_create"])
@pytest.mark.asyncio
async def test_old_unattributed_scan_is_cancelled_before_network(
    admin_client, inventory, env, monkeypatch, origin
):
    vlan = prefix(admin_client, inventory)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unscheduled scan reached the network")

    monkeypatch.setattr(adapters, "ping", forbidden)
    with env() as db:
        job = m.Job(
            kind="ipam_discover",
            target_id=vlan["id"],
            active_key="legacy:" + vlan["id"],
            result={"ipam_origin": origin},
            requested_by=db.scalar(select(m.User.id)) if origin == "vlan_create" else None,
        )
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
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover", m.Job.active_key.is_not(None)))
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


@pytest.mark.parametrize("event_type", ["ipam_ping", "ipam_update"])
def test_ping_notification_is_forwarded_without_collecting(admin_client, inventory, monkeypatch, event_type):
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
            return {"data": json.dumps({"type": event_type, "vlan_id": vlan["id"]})}

    monkeypatch.setattr(main, "redis_client", lambda: SimpleNamespace(pubsub=Subscription))
    with admin_client.websocket_connect("/api/v1/ws", headers={"origin": "http://testserver"}) as socket:
        assert socket.receive_json() == {"type": event_type, "vlan_id": vlan["id"]}
