from datetime import UTC, datetime, timedelta

from netrix import models as m
from netrix.core import now


def test_overview_widgets_require_authentication(client):
    assert client.get("/api/v1/dashboard/widgets").status_code == 401


def test_overview_widgets_use_current_scope_and_prioritize_active_alarms(admin_client, inventory, env):
    vrf_id = inventory["vrf"]["id"]
    with env() as db:
        device = m.Device(
            name="Fixture switch", management_ip="192.0.2.1", vrf_id=vrf_id,
            discovery_scope_id=inventory["scope"]["id"],
        )
        vlan = m.VLAN(name="Fixture VLAN", vid=3, vrf_id=vrf_id)
        rule = m.AlertRule(name="Fixture rule", metric="config_change")
        db.add_all([device, vlan, rule])
        db.flush()
        current_ip = m.IPAddress(address="192.0.2.10", vrf_id=vrf_id, vlan_id=vlan.id)
        moved_ip = m.IPAddress(address="192.0.2.11", vrf_id=vrf_id, vlan_id=vlan.id)
        db.add_all([current_ip, moved_ip])
        db.flush()
        for ip, recorded_address in ((current_ip, current_ip.address), (moved_ip, "192.0.2.12")):
            db.add(m.IPAMResult(
                address_id=ip.id, scope_address=recorded_address, scope_vrf=vrf_id,
                scope_vlan=vlan.id, status="problem",
            ))
        for message, severity, state, acknowledged in (
            ("Uyarı", "warning", "firing", None),
            ("Kritik", "critical", "firing", None),
            ("Görüldü", "critical", "firing", now()),
            ("Kapandı", "critical", "resolved", None),
        ):
            db.add(m.Alert(
                rule_id=rule.id, device_id=device.id, message=message, severity=severity,
                state=state, acknowledged_at=acknowledged,
            ))
        for kind, status, finished in (
            ("discovery", "queued", None),
            ("ipam_ping", "running", None),
            ("backup", "failed", now()),
            ("backup", "failed", now() - timedelta(hours=25)),
        ):
            db.add(m.Job(kind=kind, status=status, target_id=device.id, finished_at=finished))
        db.add(m.Event(device_id=device.id, kind="discovery", message="Olay"))
        db.commit()

    response = admin_client.get("/api/v1/dashboard/widgets")
    assert response.status_code == 200
    data = response.json()
    assert [row["message"] for row in data["alerts"]] == ["Kritik", "Uyarı", "Görüldü"]
    assert [row["message"] for row in data["events"]] == ["Olay"]
    assert data["charts"]["vlan_problems"] == [{"label": "Fixture VLAN · VLAN 3 · default", "count": 1}]
    assert [row["count"] for row in data["charts"]["device_types"]] == [1]
    assert {key: data["counts"][key] for key in (
        "ip_problems", "unplaced", "no_cidr", "queued", "running", "failed",
    )} == {"ip_problems": 1, "unplaced": 1, "no_cidr": 1, "queued": 1, "running": 0, "failed": 1}


def test_overview_daily_series_uses_istanbul_midnight_and_excludes_ping(admin_client, env, monkeypatch):
    from netrix import overview

    now_at = datetime(2026, 11, 14, 9, tzinfo=UTC)
    monkeypatch.setattr(overview, "now", lambda: now_at)
    with env() as db:
        for kind, ts in (
            ("discovery", datetime(2026, 11, 13, 20, 59, tzinfo=UTC)),
            ("backup", datetime(2026, 11, 13, 21, tzinfo=UTC)),
            ("ipam_ping", datetime(2026, 11, 13, 21, tzinfo=UTC)),
            ("backup", datetime(2026, 11, 7, 20, 59, tzinfo=UTC)),
        ):
            db.add(m.Job(kind=kind, status="succeeded", target_id="test", finished_at=ts))
        db.commit()
    response = admin_client.get("/api/v1/dashboard/widgets")
    assert response.status_code == 200
    jobs = response.json()["charts"]["daily"]["jobs"]
    assert len(jobs) == 7
    assert [entry["count"] for entry in jobs] == [0, 0, 0, 0, 0, 1, 1]
    assert jobs[-1]["day"] == "2026-11-14"
