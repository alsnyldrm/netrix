from datetime import timedelta

import pytest
from netrix import models as m
from netrix.configuration.diff import config_diff, redact_config
from netrix.core import now
from netrix.identity.security import decrypt
from netrix.monitoring.rates import calculate_rate
from netrix.schemas import ScopeInput
from netrix.worker import claim, execute, scope_targets
from pydantic import ValidationError
from sqlalchemy import select


class FixtureCollector:
    def __init__(self):
        self.calls = []
        self.counter = 1000

    async def collect(self, host, port, secret):
        self.calls.append(host)
        return {
            "hostname": "observed-" + host,
            "sys_description": "Fixture switch",
            "interfaces": [
                {
                    "name": "Gi1",
                    "if_index": 1,
                    "description": "fixture",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                    "speed_bps": 1000000000,
                    "oper_status": "up",
                    "counters": {
                        "in_octets": self.counter,
                        "out_octets": self.counter * 2,
                        "in_errors": 0,
                        "out_errors": 0,
                        "in_discards": 0,
                        "out_discards": 0,
                        "uptime_ticks": 100000,
                        "discontinuity_ticks": 0,
                    },
                }
            ],
            "neighbors": [
                {
                    "interface_name": "Gi1",
                    "remote_name": "uncertain-peer",
                    "remote_port": "Gi2",
                    "source": "lldp",
                }
            ],
            "tables": {},
        }


def test_scope_validation_exclusions_and_ipv6_seed(inventory):
    base = {"name": "scope", "vrf_id": inventory["vrf"]["id"], "credential_id": inventory["credential"]["id"]}
    for cidr in ("0.0.0.0/0", "10.0.0.0/8", "2001:db8::/64"):
        with pytest.raises(ValidationError):
            ScopeInput(**base, cidr=cidr)
    with pytest.raises(ValidationError):
        ScopeInput(**base, cidr="192.0.2.0/24", seeds=["198.51.100.1"])
    s = ScopeInput(
        **base, cidr="2001:db8::/64", seeds=["2001:db8::1", "2001:db8::2"], exclusions=["2001:db8::2/128"]
    )
    assert scope_targets(s) == ["2001:db8::1"]


async def test_discovery_idempotency_managed_values_and_uncertainty(admin_client, inventory, env):
    c = admin_client
    collector = FixtureCollector()
    for run in range(2):
        r = c.post("/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]})
        assert r.status_code == 202, r.text
        # A duplicate submit joins the existing logical task.
        assert (
            c.post("/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}).json()[
                "id"
            ]
            == r.json()["id"]
        )
        assert claim() == r.json()["id"]
        await execute(r.json()["id"], collector)
        assert c.get("/api/v1/jobs/" + r.json()["id"]).json()["status"] == "succeeded"
    assert len(c.get("/api/v1/devices").json()["items"]) == 2
    assert set(collector.calls) == {"192.0.2.1", "192.0.2.2"}
    assert c.get("/api/v1/links").json()["items"][0]["remote_device_id"] is None
    assert c.get("/api/v1/links").json()["items"][0]["confidence"] == 0.5
    with env() as db:
        device = db.scalar(select(m.Device))
        device.name = "Managed name"
        device_id = device.id
        db.commit()
    r = c.post("/api/v1/jobs", json={"kind": "monitor", "target_id": device_id})
    claim()
    await execute(r.json()["id"], collector)
    assert c.get("/api/v1/devices/" + device_id).json()["name"] == "Managed name"


async def test_cancel_and_lost_worker_recovery(admin_client, inventory, env):
    c = admin_client
    r = c.post("/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}).json()
    assert c.post("/api/v1/jobs/" + r["id"] + "/cancel").json()["status"] == "cancelled"
    assert claim() is None
    new = c.post("/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}).json()
    assert claim() == new["id"]
    with env() as db:
        job = db.get(m.Job, new["id"])
        job.heartbeat_at = now() - timedelta(minutes=5)
        db.commit()
    assert claim() == new["id"]
    with env() as db:
        assert db.get(m.Job, new["id"]).attempts == 2


def test_credentials_are_encrypted_and_api_redacted(admin_client, inventory, env):
    from netrix.identity.security import secret_data

    with env() as db:
        credential = db.get(m.Credential, inventory["credential"]["id"])
        assert "fixture-auth" not in credential.encrypted_secret
        assert secret_data(credential)["auth_key"] == "fixture-auth"
    for path in ("/credentials", "/credentials/" + inventory["credential"]["id"], "/audit"):
        text = admin_client.get("/api/v1" + path).text
        assert "fixture-auth" not in text
        assert "encrypted_secret" not in text


@pytest.mark.parametrize(
    "update,expected",
    [
        ({}, "valid"),
        ({"uptime_ticks": 1}, "reset"),
        ({"discontinuity_ticks": 2}, "reset"),
        ({"in_octets": 1}, "reset"),
    ],
)
def test_counter_rates_reject_resets(update, expected):
    previous = {"in_octets": 100, "out_octets": 200, "uptime_ticks": 100, "discontinuity_ticks": 0}
    current = {"in_octets": 1100, "out_octets": 2200, "uptime_ticks": 200, "discontinuity_ticks": 0, **update}
    incoming, outgoing, quality = calculate_rate(previous, current, 10, 1000000000)
    assert quality == expected
    if expected == "valid":
        assert incoming == 800 and outgoing == 1600
    else:
        assert incoming is None and outgoing is None


def test_counter_gap_and_capacity():
    p = {"in_octets": 0, "out_octets": 0, "uptime_ticks": 1, "discontinuity_ticks": 0}
    c = {**p, "in_octets": 1000}
    assert calculate_rate(p, c, 0, 1)[2] == "gap"
    assert calculate_rate(p, c, 5000, 1)[2] == "gap"
    assert calculate_rate(p, c, 1, 1)[2] == "invalid"


def test_config_redaction_and_diff():
    config = "hostname edge\nusername admin secret SUPER-SECRET\n-----BEGIN PRIVATE KEY-----\nKEYDATA\n-----END PRIVATE KEY-----\ninterface Gi1\n"
    text = redact_config(config)
    assert "SUPER-SECRET" not in text and "KEYDATA" not in text
    assert "hostname edge" in text
    diff = config_diff("hostname old\npassword HIDDEN", config)
    assert "-hostname old" in diff and "+hostname edge" in diff
    assert "SUPER-SECRET" not in diff and "HIDDEN" not in diff


async def test_encrypted_backup_history_diff_and_job_dedup(admin_client, inventory, env, monkeypatch):
    c = admin_client
    credential = c.post(
        "/api/v1/credentials",
        json={
            "name": "SSH fixture",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-secret"},
        },
    ).json()
    device = c.post(
        "/api/v1/devices",
        json={
            "name": "Managed edge",
            "management_ip": "192.0.2.1",
            "vrf_id": inventory["vrf"]["id"],
            "config_credential_id": credential["id"],
        },
    ).json()

    async def config(*args):
        return "hostname edge\npassword DONT-LEAK\n"

    monkeypatch.setattr("netrix.worker.fetch_config", config)
    for _ in range(2):
        job = c.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()
        claim()
        await execute(job["id"], FixtureCollector())
    rows = c.get("/api/v1/snapshots").json()["items"]
    assert len(rows) == 2 and not rows[0]["changed"]
    assert "DONT-LEAK" not in c.get("/api/v1/snapshots/" + rows[0]["id"] + "/content").text
    assert c.get("/api/v1/snapshots/" + rows[0]["id"] + "/diff").json()["diff"] == ""
    with env() as db:
        snap = db.get(m.Snapshot, rows[0]["id"])
        assert "DONT-LEAK" not in snap.encrypted_content
        assert "DONT-LEAK" in decrypt(snap.encrypted_content)


def test_alert_hysteresis_duration_and_recovery(admin_client, inventory, env):
    from netrix.alerting.engine import evaluate

    with env() as db:
        device = m.Device(name="D", management_ip="192.0.2.1", vrf_id=inventory["vrf"]["id"])
        db.add(device)
        db.flush()
        rule = m.AlertRule(
            name="Load",
            metric="utilization",
            threshold=80,
            recovery_threshold=60,
            duration_seconds=30,
            severity="critical",
            enabled=True,
        )
        db.add(rule)
        db.commit()
        evaluate(db, device, "utilization", 90)
        db.commit()
        alert = db.scalar(select(m.Alert))
        assert alert.state == "pending"
        alert.created_at = now() - timedelta(seconds=31)
        db.commit()
        evaluate(db, device, "utilization", 90)
        db.commit()
        assert alert.state == "firing"
        evaluate(db, device, "utilization", 70)
        db.commit()
        assert alert.state == "firing"
        evaluate(db, device, "utilization", 50)
        db.commit()
        assert alert.state == "resolved" and alert.active_key is None


def test_device_tasks_enforce_authorized_scope(admin_client, inventory):
    c = admin_client
    device = c.post(
        "/api/v1/devices",
        json={
            "name": "Outside",
            "management_ip": "198.51.100.1",
            "vrf_id": inventory["vrf"]["id"],
            "snmp_credential_id": inventory["credential"]["id"],
        },
    ).json()
    assert c.post("/api/v1/jobs", json={"kind": "monitor", "target_id": device["id"]}).status_code == 422


async def test_partial_discovery_does_not_report_every_target_successful(admin_client, inventory):
    from netrix.discovery.protocols import NetworkError

    class PartialCollector(FixtureCollector):
        async def collect(self, host, port, secret):
            if host.endswith(".2"):
                raise NetworkError("fixture unreachable")
            return await super().collect(host, port, secret)

    job = admin_client.post(
        "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
    ).json()
    claim()
    await execute(job["id"], PartialCollector())
    result = admin_client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "partial"
    assert result["result"] == {"reachable": 1, "unresponsive": 1, "total": 2}


async def test_cancellation_interrupts_inflight_discovery(admin_client, inventory, env):
    import asyncio

    from netrix.worker import discover

    started = asyncio.Event()
    finished = []

    class SlowCollector:
        async def collect(self, host, port, secret):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                finished.append(host)

    job = admin_client.post(
        "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
    ).json()
    task = asyncio.create_task(discover(job["id"], SlowCollector()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(finished) == 2
    assert admin_client.get("/api/v1/devices").json()["total"] == 0


def test_ready_success_status_and_invalid_timezone(admin_client):
    assert admin_client.get("/api/v1/health/ready").json()["status"] == "ok"
    result = admin_client.post(
        "/api/v1/sites", json={"name": "Invalid", "code": "INV", "timezone": "No/SuchZone"}
    )
    assert result.status_code == 422


def test_multiple_ports_use_highest_utilization_for_device_alarm(admin_client, inventory, env):
    from netrix.worker import sync_interfaces

    with env() as db:
        device = m.Device(name="Two ports", management_ip="192.0.2.1", vrf_id=inventory["vrf"]["id"])
        db.add(device)
        db.flush()
        db.add(
            m.AlertRule(
                name="High use",
                metric="utilization",
                threshold=80,
                recovery_threshold=60,
                duration_seconds=0,
                severity="warning",
                enabled=True,
            )
        )
        previous = m.Job(kind="monitor", target_id=device.id)
        current = m.Job(kind="monitor", target_id=device.id)
        db.add_all([previous, current])
        db.flush()
        ports = []
        for i in (1, 2):
            port = m.Interface(
                name=f"Gi{i}", device_id=device.id, if_index=i, oper_status="up", is_managed=True
            )
            db.add(port)
            db.flush()
            db.add(
                m.Sample(
                    interface_id=port.id,
                    job_id=previous.id,
                    in_octets=0,
                    out_octets=0,
                    uptime_ticks=1,
                    created_at=now() - timedelta(seconds=10),
                )
            )
            ports.append(
                {
                    "name": f"Gi{i}",
                    "if_index": i,
                    "mac_address": "",
                    "speed_bps": 1000,
                    "description": "",
                    "oper_status": "up",
                    "counters": {
                        "in_octets": 1150 if i == 1 else 10,
                        "out_octets": 0,
                        "in_errors": 0,
                        "out_errors": 0,
                        "in_discards": 0,
                        "out_discards": 0,
                        "uptime_ticks": 200,
                        "discontinuity_ticks": 0,
                    },
                }
            )
        db.commit()
        sync_interfaces(db, device, {"interfaces": ports}, current.id)
        db.commit()
        alert = db.scalar(select(m.Alert))
        assert alert and alert.state == "firing"


@pytest.mark.parametrize(
    "config",
    [
        '{"hostname":"edge","auth_key":\n"MUST-HIDE","nested":{"password":"MUST-HIDE"}}',
        "<config><hostname>edge</hostname><password>\nMUST-HIDE\n</password></config>",
        '<config><entry name="password"><value>MUST-HIDE</value></entry></config>',
        "hostname edge\nkey-string MUST-HIDE",
        "hostname edge\npassword:\nMUST-HIDE",
        '{"password":\nMUST-HIDE',
    ],
)
def test_multiline_structured_configuration_secrets_are_redacted(config):
    assert "MUST-HIDE" not in redact_config(config)


def test_manual_inventory_is_not_presented_as_completed_discovery(admin_client):
    vrf = admin_client.get("/api/v1/vrfs").json()["items"][0]["id"]
    assert (
        admin_client.post(
            "/api/v1/devices", json={"name": "Manual device", "management_ip": "192.0.2.5", "vrf_id": vrf}
        ).status_code
        == 201
    )
    counts = admin_client.get("/api/v1/dashboard").json()["counts"]
    assert counts["devices"] == 1 and counts["successful_discoveries"] == 0 and counts["reachable"] == 0
