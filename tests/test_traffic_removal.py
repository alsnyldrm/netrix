"""Removed collection cannot be reached through APIs, queues or SNMP clients."""

import pytest
from netrix import models as m
from netrix.core import Base
from netrix.discovery.protocols import TABLES, SNMPCollector
from netrix.worker import execute
from sqlalchemy import select


def test_removed_routes_and_schema(admin_client):
    paths = admin_client.get("/api/v1/openapi.json").json()["paths"]
    assert not any("traffic" in p or p.endswith("/live") and "health" not in p for p in paths)
    assert not {"interface_samples", "ip_traffic"} & Base.metadata.tables.keys()
    for model in (m.Device, m.Interface):
        assert "monitoring_enabled" not in model.__table__.columns
    assert not hasattr(SNMPCollector, "interface_counters")
    assert (
        not {"in_octets", "out_octets", "in_errors", "out_errors", "in_discards", "out_discards"}
        & TABLES.keys()
    )
    assert admin_client.get("/api/v1/traffic").status_code == 404
    assert admin_client.get("/api/v1/ipam/addresses/missing/traffic").status_code == 404
    assert admin_client.post("/api/v1/ipam/addresses/missing/live", json={}).status_code in (404, 405)


@pytest.mark.parametrize("kind", ["monitor", "ipam_live"])
async def test_removed_job_kinds_rejected_even_from_old_queue(admin_client, env, kind):
    assert admin_client.post("/api/v1/jobs", json={"kind": kind, "target_id": "missing"}).status_code == 422
    with env() as db:
        job = m.Job(kind=kind, target_id="missing", status="running", active_key=kind)
        db.add(job)
        db.commit()
        id = job.id
    await execute(id)
    with env() as db:
        job = db.get(m.Job, id)
        assert job.status == "cancelled" and job.active_key is None
        assert not db.scalar(select(m.Observation.id))


@pytest.mark.parametrize("metric", ["availability", "utilization", "no_data"])
def test_removed_alarm_metrics_rejected(admin_client, metric):
    assert admin_client.post("/api/v1/rules", json={"name": "Removed", "metric": metric}).status_code == 422


def test_configuration_change_alerts_still_work(env):
    from netrix.alerting.engine import evaluate

    with env() as db:
        vrf = m.VRF(name="Fixture")
        db.add(vrf)
        db.flush()
        device = m.Device(name="Fixture", management_ip="192.0.2.1", vrf_id=vrf.id)
        rule = m.AlertRule(name="Config changed", metric="config_change")
        db.add_all([device, rule])
        db.flush()
        evaluate(db, device, "config_change", 1)
        db.flush()
        alert = db.scalar(select(m.Alert))
        assert alert.state == "firing"
        evaluate(db, device, "config_change", 0)
        assert alert.state == "resolved" and alert.active_key is None
