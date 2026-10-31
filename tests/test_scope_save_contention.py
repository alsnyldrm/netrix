"""Scope metadata must not wait behind IPAM's VRF-wide writer mutex."""

from netrix import models as m
from netrix import services as svc
from sqlalchemy import select
from sqlalchemy.exc import OperationalError


def test_scope_create_update_bypass_inventory_writer_mutex(admin_client, inventory, monkeypatch, env):
    def blocked(*args, **kwargs):
        raise AssertionError("Scope metadata waited on the IP inventory writer mutex")

    monkeypatch.setattr(svc, "lock_vrf", blocked)
    payload = dict(
        name="VLAN-60",
        cidr="10.6.0.0/21",
        vrf_id=inventory["vrf"]["id"],
        credential_ids=[inventory["credential"]["id"]],
    )
    response = admin_client.post("/api/v1/scopes", json=payload)
    assert response.status_code == 201, response.text
    id = response.json()["id"]
    response = admin_client.put("/api/v1/scopes/" + id, json={**payload, "name": "Updated"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated"
    assert admin_client.get("/api/v1/jobs").json()["total"] == 0
    with env() as db:
        assert len(list(db.scalars(select(m.ScopeCredential).where(m.ScopeCredential.scope_id == id)))) == 1
    assert admin_client.post("/api/v1/scopes", json={**payload, "vrf_id": "missing"}).status_code in (
        404,
        422,
    )


def test_writer_mutex_versions_are_transactional_and_separate_from_parent(env):
    with env() as db:
        vrfs = [m.VRF(name="First"), m.VRF(name="Second")]
        db.add_all(vrfs)
        db.commit()
        first, second = [v.id for v in vrfs]
        original = db.get(m.VRF, first).lock_version
        svc.lock_vrf(db, first)
        svc.lock_vrf(db, first)
        svc.lock_vrf(db, second)
        assert db.get(m.VRF, first).lock_version == original
        assert db.get(m.SystemState, "vrf:" + first).value == "2"
        assert db.get(m.SystemState, "vrf:" + second).value == "1"
        db.rollback()
        assert db.get(m.SystemState, "vrf:" + first) is None
        svc.lock_vrf(db, first)
        db.commit()
        assert db.get(m.SystemState, "vrf:" + first).value == "1"


def test_database_failure_logs_code_without_sql_or_secrets(admin_client, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OperationalError(
            "SQL-MUST-NOT-LEAK",
            {"secret": "PARAMETER-MUST-NOT-LEAK"},
            Exception(1205, "ERROR-TEXT-MUST-NOT-LEAK"),
        )

    monkeypatch.setattr(svc, "save_resource", fail)
    response = admin_client.post("/api/v1/scopes", json={})
    assert response.status_code == 503
    assert "method=POST path=/api/v1/scopes code=1205" in caplog.text
    assert "MUST-NOT-LEAK" not in caplog.text + response.text
