"""Read budgets and freshness: optimizations must keep connection evidence correct."""

from contextlib import contextmanager

from netrix import models as m
from netrix import services
from netrix.core import engine
from netrix.ipam import racks, read_cache, service
from netrix.main import dashboard_data
from sqlalchemy import event
from test_ipam_endpoint_connections import endpoint


@contextmanager
def queries():
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine(), "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine(), "before_cursor_execute", capture)


def test_detail_resolves_once_and_cache_is_invalidated(admin_client, inventory, env, monkeypatch):
    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        service.observe(db, vlan, row.address, "dns", "system", {"hostname": "before.example.test"})
        db.commit()
        id = row.id
    calls = []
    original = service.observations

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "observations", counted)
    path = f"/api/v1/ipam/addresses/{id}"
    with queries() as sql:
        first = admin_client.get(path)
    assert sum("FROM ip_observations" in statement for statement in sql) == 1
    assert first.status_code == 200
    assert first.json()["hostname"] == "before.example.test"
    assert len(calls) == 1
    assert "hit" in admin_client.get(path).headers["Server-Timing"]
    assert len(calls) == 1
    with env() as db:
        row = db.get(m.IPAddress, id)
        service.observe(
            db, db.get(m.VLAN, row.vlan_id), row.address, "dns", "system", {"hostname": "after.example.test"}
        )
        db.commit()
    services.publish()
    assert admin_client.get(path).json()["hostname"] == "after.example.test"
    assert len(calls) == 2


def test_catalog_does_not_fetch_hidden_snapshot_or_secret(admin_client, inventory, env):
    with env() as db:
        db.add(
            m.Integration(
                name="VMware",
                kind="vcenter",
                host="vc.test",
                port=443,
                enabled=True,
                encrypted_secret="fixture",
            )
        )
        db.commit()
    with env() as db, queries() as sql:
        result = services.list_resource(db, "integrations")
        assert len(result["items"]) == 1
        row_queries = [query for query in sql if "count(" not in query.lower()]
        assert len(row_queries) == 1
        assert "integrations.evidence" not in row_queries[0]
        assert "integrations.encrypted_secret" not in row_queries[0]
        assert "evidence" not in result["items"][0]


def test_snapshot_tables_do_not_transfer_encrypted_configs(admin_client, inventory, env):
    from netrix.inventory.management import query

    with env() as db:
        device = m.Device(name="Server", management_ip="192.0.2.1", vrf_id=inventory["vrf"]["id"])
        db.add(device)
        db.flush()
        job = m.Job(kind="backup", target_id=device.id, status="succeeded")
        db.add(job)
        db.flush()
        db.add(
            m.Snapshot(
                device_id=device.id,
                job_id=job.id,
                fingerprint="a" * 64,
                size_bytes=1_000_000,
                encrypted_content="x" * 1_000_000,
            )
        )
        db.commit()
    for read in (lambda db: query(db, "snapshots"), lambda db: services.list_resource(db, "snapshots")):
        with env() as db, queries() as sql:
            result = read(db)
            assert result["total"] == 1
            assert "encrypted_content" not in result["items"][0]
            assert not any(
                "snapshots.encrypted_content" in statement
                for statement in sql
                if "count(" not in statement.lower()
            )


def test_rack_read_has_constant_query_count_and_correct_model_images(admin_client, inventory, env):
    with env() as db:
        cabinet = m.Cabinet(name="42U", units=42, site_id=None)
        db.add(cabinet)
        db.flush()
        for unit in range(1, 21):
            device = m.Device(
                name=f"Device {unit}",
                management_ip=f"192.0.2.{unit}",
                vrf_id=inventory["vrf"]["id"],
                vendor="HPE",
                model="JL675A",
            )
            db.add(device)
            db.flush()
            db.add(m.RackPlacement(cabinet_id=cabinet.id, device_id=device.id, start_unit=unit, units=1))
        db.commit()
        id = cabinet.id
    with env() as db, queries() as sql:
        result = racks.detail(db, id)
        assert len(result["placements"]) == 20
        assert all(
            row["image"]["url"].startswith("https://assets.ext.hpe.com/") for row in result["placements"]
        )
        assert len(sql) <= 5, sql


def test_dashboard_aggregates_in_two_round_trips(admin_client, inventory, env):
    with env() as db, queries() as sql:
        result = dashboard_data(db)
        assert result["counts"]["sites"] == 0
        assert result["counts"]["config_changes"] == 0
        assert len(sql) == 2
