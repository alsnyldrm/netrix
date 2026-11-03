"""Authorization, secret isolation and compact workspace regression tests; no network."""

import json
import time
from contextlib import nullcontext

import pytest
from netrix import models as m
from netrix.access import ephemeral as e
from netrix.access import runtime, service
from netrix.access.schemas import Preferences
from netrix.identity.security import decrypt, hasher
from sqlalchemy import func, select


@pytest.fixture
def target(admin_client, inventory, env):
    with env() as db:
        device = m.Device(
            name="SSH fixture",
            management_ip="192.0.2.1",
            vrf_id=inventory["vrf"]["id"],
            discovery_scope_id=inventory["scope"]["id"],
            adapter="linux",
        )
        user = m.User(
            email="viewer@example.test",
            display_name="Viewer",
            password_hash=hasher.hash("fixture-long-password"),
            role="viewer",
        )
        db.add_all([device, user])
        db.commit()
        return device.id, user.id


def profile(client):
    return client.put(
        "/api/v1/access/ssh-profile",
        json={
            "username": "personal",
            "password": "private-password",
            "port": 2222,
            "initial_command": "terminal length 0",
        },
    )


def test_profile_is_encrypted_and_no_secret_echo(admin_client, env):
    response = profile(admin_client)
    assert response.status_code == 200, response.text
    assert response.json()["has_password"] is True
    assert "private-password" not in response.text
    assert "password" not in response.json()
    with env() as db:
        row = db.scalar(select(m.UserWorkspace))
        assert "private-password" not in row.encrypted_ssh
        assert json.loads(decrypt(row.encrypted_ssh))["password"] == "private-password"
    response = admin_client.put("/api/v1/access/ssh-profile", json={"username": "updated", "port": 22})
    assert response.status_code == 200
    with env() as db:
        assert (
            json.loads(decrypt(db.scalar(select(m.UserWorkspace)).encrypted_ssh))["password"]
            == "private-password"
        )
    response = admin_client.put(
        "/api/v1/access/ssh-profile",
        json={"username": "updated", "password": "secret-validation-marker", "port": 0},
    )
    assert response.status_code == 422
    assert "secret-validation-marker" not in response.text
    assert admin_client.delete("/api/v1/access/ssh-profile").status_code == 204
    assert admin_client.get("/api/v1/access/ssh-profile").json()["has_password"] is False


def test_preferences_single_row_validation_and_saved_commands(admin_client, env):
    for palette in ("cobalt", "teal", "violet", "amber", "forest", "slate"):
        result = admin_client.put("/api/v1/access/preferences", json={"palette": palette, "timezone": "UTC"})
        assert result.status_code == 200
    assert (
        admin_client.put("/api/v1/access/preferences", json={"timezone": "invented/zone"}).status_code == 422
    )
    command = {"id": "one", "name": "Status", "command": "show version secret-marker"}
    assert admin_client.put("/api/v1/access/commands", json={"items": [command]}).status_code == 200
    assert admin_client.get("/api/v1/access/commands").json()["items"] == [command]
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.UserWorkspace)) == 1
        row = db.scalar(select(m.UserWorkspace))
        assert "secret-marker" not in row.encrypted_commands
    assert admin_client.put("/api/v1/access/commands", json={"items": [command] * 51}).status_code == 422
    assert Preferences().features == ["saved_commands", "session_dock"]


def test_ssh_role_enforced_and_groups_are_personal(admin_client, target, env):
    device_id, user_id = target
    with env() as db:
        with pytest.raises(Exception) as exc:
            service.authorize_device(db, db.get(m.User, user_id), device_id)
        assert exc.value.status_code == 403
    result = admin_client.post(
        "/api/v1/access/groups", json={"name": "Admin personal", "device_ids": [device_id]}
    )
    group_id = result.json()["id"]
    result = admin_client.put(f"/api/v1/users/{user_id}/roles", json={"role": "viewer", "ssh_access": True})
    assert result.status_code == 200, result.text
    assert result.json()["role"] == "viewer"
    with env() as db:
        assert service.authorize_device(db, db.get(m.User, user_id), device_id).id == device_id
    admin_client.post("/api/v1/auth/logout")
    assert (
        admin_client.post(
            "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "fixture-long-password"}
        ).status_code
        == 200
    )
    assert admin_client.get("/api/v1/access/groups").json()["items"] == []
    assert admin_client.get("/api/v1/access/ssh-profile").json()["has_password"] is False
    assert admin_client.get("/api/v1/access/devices").json()["items"][0]["id"] == device_id
    assert admin_client.put(f"/api/v1/access/groups/{group_id}", json={"name": "Stolen"}).status_code == 404
    assert admin_client.delete(f"/api/v1/access/groups/{group_id}").status_code == 404
    assert (
        admin_client.put(
            f"/api/v1/users/{user_id}/roles", json={"role": "admin", "ssh_access": True}
        ).status_code
        == 403
    )
    assert (
        admin_client.post("/api/v1/access/groups", json={"name": "Grant", "ssh_enabled": True}).status_code
        == 422
    )
    personal = admin_client.post(
        "/api/v1/access/groups", json={"name": "Personal", "device_ids": [device_id]}
    )
    assert personal.status_code == 201
    assert "user_ids" not in personal.json() and "ssh_enabled" not in personal.json()
    with env() as db:
        db.get(m.User, user_id).ssh_access = False
        db.commit()
        with pytest.raises(Exception) as exc:
            service.authorize_device(db, db.get(m.User, user_id), device_id)
        assert exc.value.status_code == 403
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 403
    # Personal grouping remains available without the network execution role.
    assert (
        admin_client.put(
            f"/api/v1/access/groups/{personal.json()['id']}",
            json={"name": "Personal", "device_ids": [device_id]},
        ).status_code
        == 200
    )


def test_device_filters_and_cross_page_selection(admin_client, target, inventory, env):
    with env() as db:
        for n in range(205):
            db.add(
                m.Device(
                    name=f"Filter {n:03}",
                    management_ip=f"198.51.100.{n + 1}",
                    vrf_id=inventory["vrf"]["id"],
                    discovery_scope_id=inventory["scope"]["id"],
                    model="CX6200" if n < 150 else "CX6300",
                    vendor="Aruba",
                    software_version="10.13",
                )
            )
        db.commit()
    filters = json.dumps(
        [
            {"field": "model", "op": "eq", "value": "CX6200", "join": "and"},
            {"field": "software_version", "op": "contains", "value": "10.13", "join": "and"},
        ]
    )
    params = {"filters": filters}
    page = admin_client.get("/api/v1/access/devices", params=params).json()
    assert page["total"] == 150 and len(page["items"]) == 100 and page["has_more"]
    assert {"model", "software_version", "vendor", "kind", "site_name", "vrf_name"} <= {
        c["key"] for c in page["columns"]
    }
    assert all(d["model"] == "CX6200" for d in page["items"])
    second = admin_client.get("/api/v1/access/devices", params={**params, "offset": 100}).json()
    assert len(second["items"]) == 50 and not second["has_more"]
    ids = admin_client.get("/api/v1/access/device-selection", params=params).json()["ids"]
    assert len(set(ids)) == 150
    assert set(ids) == {d["id"] for d in page["items"] + second["items"]}
    saved = admin_client.post("/api/v1/access/groups", json={"name": "Filtered", "device_ids": ids})
    assert saved.status_code == 201 and len(saved.json()["device_ids"]) == 150
    assert admin_client.get("/api/v1/access/device-filter-values", params={"field": "model"}).json()[
        "values"
    ] == ["CX6200", "CX6300"]
    assert (
        admin_client.get("/api/v1/access/device-filter-values", params={"field": "password_hash"}).status_code
        == 422
    )
    bad = json.dumps([{"field": "password_hash", "op": "eq", "value": "x", "join": "and"}])
    assert admin_client.get("/api/v1/access/device-selection", params={"filters": bad}).status_code == 422
    with env() as db:
        me = db.scalar(select(m.User).where(m.User.role == "admin"))
        me_id = me.id
    assert (
        admin_client.put(
            f"/api/v1/users/{me_id}/roles", json={"role": "viewer", "ssh_access": False}
        ).status_code
        == 409
    )


def test_inventory_boundary_cascade_and_profile_requirement(admin_client, target, env):
    device_id, user_id = target
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 409
    result = admin_client.post(
        "/api/v1/access/groups",
        json={"name": "Fixture", "device_ids": [device_id]},
    )
    assert result.status_code == 201
    assert admin_client.delete("/api/v1/access/groups/" + result.json()["id"]).status_code == 204
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.AccessGroupDevice)) == 0
        device = db.get(m.Device, device_id)
        device.discovery_scope_id = None
        db.commit()
    assert (
        admin_client.post(
            "/api/v1/access/groups", json={"name": "Outside", "device_ids": [device_id]}
        ).status_code
        == 422
    )
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 404


class EphemeralRedis:
    def __init__(self):
        self.data = {e.PREFIX + "heartbeat": str(time.time())}
        self.zsets = {}
        self.queue = []
        self.ttls = {}

    def hmget(self, key, fields):
        return [None for _ in fields]

    def pipeline(self, **kwargs):
        class Pipeline:
            def __init__(pipe):
                pipe.calls = []

            def __enter__(pipe):
                return pipe

            def __exit__(pipe, *args):
                pass

            def set(pipe, *args, **kwargs):
                pipe.calls.append((self.set, args, kwargs))

            def zadd(pipe, *args, **kwargs):
                pipe.calls.append((self.zadd, args, kwargs))

            def rpush(pipe, *args, **kwargs):
                pipe.calls.append((self.rpush, args, kwargs))

            def execute(pipe):
                for call, args, kwargs in pipe.calls:
                    call(*args, **kwargs)

        return Pipeline()

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.data:
            return False
        self.data[key] = value
        self.ttls[key] = kwargs.get("ex")
        return True

    def lock(self, *args, **kwargs):
        return nullcontext()

    def zremrangebyscore(self, key, low, high):
        self.zsets[key] = {k: v for k, v in self.zsets.get(key, {}).items() if v > high}

    def zrange(self, key, *args):
        return list(self.zsets.get(key, {}))

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def rpush(self, key, value):
        self.queue.append(value)


def test_admission_is_bounded_and_owner_isolation(admin_client, target, monkeypatch):
    device_id, user_id = target
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    assert profile(admin_client).status_code == 200
    sessions = [
        admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}) for _ in range(16)
    ]
    assert all(r.status_code == 201 for r in sessions)
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 429
    id = sessions[0].json()["id"]
    assert admin_client.get("/api/v1/access/sessions/" + id).status_code == 200
    assert e.read(memory, "session", id)["auth_hash"] not in sessions[0].text
    assert "SSH fixture" not in memory.data[e.key("session", id)]
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "fixture-long-password"}
    )
    assert admin_client.get("/api/v1/access/sessions/" + id).status_code == 404
    assert admin_client.delete("/api/v1/access/sessions/" + id).status_code == 404
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 403
    memory.data.pop(e.PREFIX + "heartbeat")
    with pytest.raises(Exception) as exc:
        e.admit("session", {"user_id": user_id})
    assert exc.value.status_code == 503


def test_batch_all_or_nothing_no_unscoped_target(admin_client, target, env, monkeypatch):
    device_id, user_id = target
    profile(admin_client)
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    assert (
        admin_client.post(
            "/api/v1/access/batches", json={"device_ids": [device_id, "missing"], "command": "show version"}
        ).status_code
        == 404
    )
    assert not memory.queue
    result = admin_client.post(
        "/api/v1/access/batches", json={"device_ids": [device_id, device_id], "command": "show version"}
    )
    assert result.status_code == 202, result.text
    id = result.json()["id"]
    output = admin_client.get("/api/v1/access/batches/" + id).json()
    assert len(output["targets"]) == 1
    assert "command" not in output and "auth_hash" not in output
    assert (
        admin_client.post(
            "/api/v1/access/batches", json={"device_ids": [device_id], "command": "show version"}
        ).status_code
        == 429
    )
    assert admin_client.delete("/api/v1/access/batches/" + id).status_code == 204
    assert memory.data[e.key("cancel", id)] == "1"
    assert memory.ttls[e.key("cancel", id)] == e.TTL
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        value = e.read(memory, "batch", id)
        assert runtime.connection_data(value, device_id)[1]["username"] == "personal"
        db.get(m.User, user_id).is_active = False


@pytest.mark.asyncio
async def test_real_prompt_comware_and_ansi():
    class Stream:
        def __init__(self, data):
            self.data = iter(data)

        async def read(self, size):
            return next(self.data, "")

    class Process:
        pass

    process = Process()
    process.stdout = Stream(["show version\r\nHP 1950\r\n", "<SW-01>"])
    assert "HP 1950" in await runtime.read_prompt(process)
    process.stdout = Stream(["\x1b[32mSW-01#\x1b[0m"])
    assert "SW-01#" in await runtime.read_prompt(process)


@pytest.mark.asyncio
async def test_batch_concurrency_cancellation_and_bounded_outputs(monkeypatch):
    import asyncio

    class Client:
        cancelled = False

        async def get(self, key):
            return "1" if self.cancelled else None

    client = Client()
    active = peak = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_state(*args, **kwargs):
        pass

    async def run(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 4:
            started.set()
        try:
            await release.wait()
            return "x" * 65536, True
        finally:
            active -= 1

    monkeypatch.setattr(runtime, "state", fake_state)
    monkeypatch.setattr(runtime, "target_state", fake_state)
    monkeypatch.setattr(runtime, "connection_data", lambda *args: (None, None))
    monkeypatch.setattr(runtime, "run_command", run)
    value = {
        "command": "show version",
        "timeout": 5,
        "targets": [{"device_id": str(n), "status": "queued", "output": ""} for n in range(40)],
    }
    task = asyncio.create_task(runtime.run_batch(client, "fixture", value))
    await asyncio.wait_for(started.wait(), 2)
    assert peak == 4
    release.set()
    await asyncio.wait_for(task, 3)
    assert all(t["status"] == "succeeded" for t in value["targets"])
    assert sum(len(t["output"].encode()) for t in value["targets"]) < 2 * 1024 * 1024 + 4000
    assert any("Toplam çıktı sınırı" in t["output"] for t in value["targets"])
    release.clear()
    started.clear()
    value = {
        "command": "hang",
        "timeout": 5,
        "targets": [{"device_id": str(n), "status": "queued", "output": ""} for n in range(8)],
    }
    task = asyncio.create_task(runtime.run_batch(client, "cancel", value))
    await asyncio.wait_for(started.wait(), 2)
    client.cancelled = True
    await asyncio.wait_for(task, 2)
    assert value["status"] == "cancelled"
    assert all(t["status"] == "cancelled" for t in value["targets"])
    assert active == 0
