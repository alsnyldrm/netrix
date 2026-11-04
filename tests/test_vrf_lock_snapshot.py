"""The VRF writer mutex must survive MariaDB snapshot-isolation conflicts (1020)."""

import pytest
from netrix import models as m
from netrix import services as svc
from sqlalchemy.exc import OperationalError


def conflict_once(db, code=1020):
    original, calls = db.execute, []

    def execute(statement, *args, **kwargs):
        calls.append(statement)
        if len(calls) == 1:
            raise OperationalError("redacted", {}, Exception(code, "fixture conflict"))
        return original(statement, *args, **kwargs)

    db.execute = execute
    return calls


def test_read_only_transaction_drops_stale_snapshot_and_takes_mutex(env):
    with env() as db:
        vrf = m.VRF(name="Snapshot")
        db.add(vrf)
        db.commit()
        # Authentication and form validation read before the mutex is reached.
        assert db.get(m.VRF, vrf.id).name == "Snapshot"
        calls = conflict_once(db)
        assert svc.lock_vrf(db, vrf.id).id == vrf.id
        db.commit()
        assert len(calls) == 2
        assert db.get(m.SystemState, "vrf:" + vrf.id).value == "1"


@pytest.mark.parametrize("pending", ["flushed", "unflushed"])
def test_transaction_with_writes_never_rewinds(env, pending):
    with env() as db:
        vrf = m.VRF(name="Owner")
        db.add(vrf)
        db.commit()
        other = m.VRF(name="Caller work")
        db.add(other)
        if pending == "flushed":
            db.flush()
        calls = conflict_once(db)
        with pytest.raises(OperationalError):
            svc.lock_vrf(db, vrf.id)
        assert len(calls) == 1
        assert other in db


def test_other_lock_errors_are_not_retried(env):
    with env() as db:
        vrf = m.VRF(name="Timeout")
        db.add(vrf)
        db.commit()
        db.get(m.VRF, vrf.id)
        calls = conflict_once(db, 1205)
        with pytest.raises(OperationalError):
            svc.lock_vrf(db, vrf.id)
        assert len(calls) == 1


@pytest.mark.parametrize("code", [1020, 1213])
def test_concurrent_change_is_conflict_not_outage(admin_client, monkeypatch, code):
    def fail(*args, **kwargs):
        raise OperationalError("redacted", {}, Exception(code, "fixture conflict"))

    monkeypatch.setattr(svc, "save_resource", fail)
    response = admin_client.put("/api/v1/addresses/fixture", json={})
    assert response.status_code == 409
    assert response.json()["detail"] == "Kayıt eşzamanlı olarak değişti; yeniden deneyin"
