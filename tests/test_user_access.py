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
    devices = client.get("/api/v1/access/devices").json()["items"]
    groups = client.get("/api/v1/access/groups").json()["items"]
    group_ids = [g["id"] for g in groups if not g["ssh_profile_id"]]
    assigned = {id for g in groups for id in g["device_ids"]}
    ids = [d["id"] for d in devices if d["id"] not in assigned]
    if ids:
        result = client.post("/api/v1/access/groups", json={"name": "Profile fixture", "device_ids": ids})
        assert result.status_code == 201, result.text
        group_ids.append(result.json()["id"])
    return client.post(
        "/api/v1/access/ssh-profiles",
        json={
            "name": "Personal",
            "group_ids": group_ids,
            "username": "personal",
            "password": "private-password",
            "port": 2222,
            "initial_command": "terminal length 0",
        },
    )


def test_profile_is_encrypted_and_no_secret_echo(admin_client, env):
    response = profile(admin_client)
    assert response.status_code == 201, response.text
    assert response.json()["has_password"] is True
    assert "private-password" not in response.text
    assert "password" not in response.json()
    with env() as db:
        row = db.scalar(select(m.UserSSHProfile))
        assert "private-password" not in row.encrypted_ssh
        assert json.loads(decrypt(row.encrypted_ssh))["password"] == "private-password"
    response = admin_client.put(
        f"/api/v1/access/ssh-profiles/{response.json()['id']}",
        json={"name": "Personal", "username": "updated", "port": 22},
    )
    assert response.status_code == 200
    with env() as db:
        assert (
            json.loads(decrypt(db.scalar(select(m.UserSSHProfile)).encrypted_ssh))["password"]
            == "private-password"
        )
    response = admin_client.post(
        "/api/v1/access/ssh-profiles",
        json={"name": "Invalid", "username": "updated", "password": "secret-validation-marker", "port": 0},
    )
    assert response.status_code == 422
    assert "secret-validation-marker" not in response.text
    id = admin_client.get("/api/v1/access/ssh-profiles").json()["items"][0]["id"]
    assert admin_client.delete(f"/api/v1/access/ssh-profiles/{id}").status_code == 204
    assert admin_client.get("/api/v1/access/ssh-profiles").json()["items"] == []


def test_preferences_single_row_validation_and_saved_commands(admin_client, env):
    for palette in (
        "cobalt",
        "teal",
        "violet",
        "amber",
        "forest",
        "slate",
        "rose",
        "cyan",
        "orange",
        "indigo",
    ):
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


def test_terminal_preferences_preserve_workspace_and_validate_bounds(admin_client, env):
    original = {"palette": "amber", "design": "focus", "timezone": "UTC", "features": []}
    assert admin_client.put("/api/v1/access/preferences", json=original).status_code == 200
    defaults = admin_client.get("/api/v1/access/preferences").json()["terminal"]
    assert defaults["font"] == "ubuntu" and defaults["background"] == "#300a24"
    terminal = {
        **defaults,
        "font": "plex",
        "font_size": 22,
        "font_weight": 700,
        "background": "#ffffff",
        "commands_width": 480,
        "commands_collapsed": True,
    }
    response = admin_client.put("/api/v1/access/preferences/terminal", json=terminal)
    assert response.status_code == 200
    saved = admin_client.get("/api/v1/access/preferences").json()
    assert saved["terminal"] == terminal
    assert all(saved[key] == value for key, value in original.items())
    for invalid in (
        {"font": "url(https://untrusted.test/font)"},
        {"font_size": 29},
        {"font_size": 9},
        {"font_weight": 200},
        {"background": "red;display:none"},
        {"background": "#00000000"},
        {"commands_width": 239},
        {"commands_width": 561},
        {"unknown": True},
    ):
        result = admin_client.put("/api/v1/access/preferences/terminal", json={**terminal, **invalid})
        assert result.status_code == 422
    assert admin_client.get("/api/v1/access/preferences").json() == saved
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.UserWorkspace)) == 1


def test_saved_command_edit_retains_identity_order_and_encryption(admin_client, env):
    items = [
        {"id": "one", "name": "Conf", "command": "show version"},
        {"id": "two", "name": "running conf", "command": "show running-config"},
    ]
    assert admin_client.put("/api/v1/access/commands", json={"items": items}).status_code == 200
    items[0] = {**items[0], "name": "Configuration", "command": "edited-secret-marker"}
    response = admin_client.put("/api/v1/access/commands", json={"items": items})
    assert response.status_code == 200
    assert admin_client.get("/api/v1/access/commands").json()["items"] == items
    with env() as db:
        row = db.scalar(select(m.UserWorkspace))
        assert "edited-secret-marker" not in row.encrypted_commands


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
    assert admin_client.get("/api/v1/access/ssh-profiles").json()["items"] == []
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

    def expire(self, key, ttl):
        return True

    def delete(self, key):
        return self.data.pop(key, None) is not None

    def zrem(self, key, id):
        self.zsets.get(key, {}).pop(id, None)

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def rpush(self, key, value):
        self.queue.append(value)


def test_admission_is_bounded_and_owner_isolation(admin_client, target, monkeypatch):
    device_id, user_id = target
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    assert profile(admin_client).status_code == 201
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


def test_profile_idle_timeout_legacy_defaults_validation_and_session_snapshot(
    admin_client, target, env, monkeypatch
):
    from netrix.identity.security import encrypt

    device_id, _ = target
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    saved = profile(admin_client).json()
    id = saved["id"]
    assert saved["idle_timeout_minutes"] == 15
    # Existing encrypted profiles work without a schema/data migration.
    with env() as db:
        row = db.get(m.UserSSHProfile, id)
        data = json.loads(decrypt(row.encrypted_ssh))
        data.pop("idle_timeout_minutes")
        row.encrypted_ssh = encrypt(json.dumps(data))
        db.commit()
    assert admin_client.get("/api/v1/access/ssh-profiles").json()["items"][0]["idle_timeout_minutes"] == 15
    payload = {
        "name": saved["name"],
        "username": "personal",
        "group_ids": saved["group_ids"],
        "idle_timeout_minutes": 7,
    }
    assert (
        admin_client.put(f"/api/v1/access/ssh-profiles/{id}", json=payload).json()["idle_timeout_minutes"]
        == 7
    )
    with env() as db:
        data = json.loads(decrypt(db.get(m.UserSSHProfile, id).encrypted_ssh))
        assert data["idle_timeout_minutes"] == 7 and data["password"] == "private-password"
    session = admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).json()
    assert session["idle_timeout_minutes"] == 7
    assert e.read(memory, "session", session["id"])["idle_timeout_minutes"] == 7
    for invalid in (0, -1, 241, 1.5, None):
        response = admin_client.put(
            f"/api/v1/access/ssh-profiles/{id}", json={**payload, "idle_timeout_minutes": invalid}
        )
        assert response.status_code == 422, response.text
    assert (
        admin_client.put(
            f"/api/v1/access/ssh-profiles/{id}", json={**payload, "idle_timeout_minutes": 1}
        ).status_code
        == 200
    )
    # An existing session keeps its admitted policy, including after tab transfer.
    assert admin_client.get(f"/api/v1/access/sessions/{session['id']}").json()["idle_timeout_minutes"] == 7
    second = admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).json()
    assert second["idle_timeout_minutes"] == 1
    assert (
        admin_client.post(
            "/api/v1/access/sessions", json={"device_id": device_id, "idle_timeout_minutes": 240}
        ).status_code
        == 422
    )
    assert (
        admin_client.put(
            f"/api/v1/access/ssh-profiles/{id}", json={**payload, "idle_timeout_minutes": 240}
        ).status_code
        == 200
    )


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


def test_named_profiles_route_by_group_and_prevent_duplicate_membership(
    admin_client, target, env, monkeypatch
):
    device_id, other_user_id = target
    with env() as db:
        device = db.get(m.Device, device_id)
        second = m.Device(
            name="Second switch",
            management_ip="192.0.2.2",
            vrf_id=device.vrf_id,
            discovery_scope_id=device.discovery_scope_id,
        )
        db.add(second)
        db.commit()
        second_id = second.id
    a = admin_client.post("/api/v1/access/groups", json={"name": "A", "device_ids": [device_id]}).json()
    b = admin_client.post("/api/v1/access/groups", json={"name": "B", "device_ids": [second_id]}).json()
    duplicate = admin_client.post(
        "/api/v1/access/groups", json={"name": "Duplicate", "device_ids": [device_id]}
    )
    assert duplicate.status_code == 409 and "A" in duplicate.json()["detail"]
    assert (
        admin_client.put(
            f"/api/v1/access/groups/{b['id']}", json={"name": "B", "device_ids": [device_id]}
        ).status_code
        == 409
    )
    assert admin_client.get("/api/v1/access/groups").json()["items"][1]["device_ids"] == [second_id]
    payload = {
        "name": "Switches",
        "username": "switch-admin",
        "password": "first-secret",
        "port": 2222,
        "group_ids": [a["id"]],
    }
    first = admin_client.post("/api/v1/access/ssh-profiles", json=payload)
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    second_profile = admin_client.post(
        "/api/v1/access/ssh-profiles",
        json={
            **payload,
            "name": "Routers",
            "username": "router-admin",
            "password": "second-secret",
            "port": 2200,
            "group_ids": [b["id"]],
        },
    )
    assert second_profile.status_code == 201
    assert (
        admin_client.post("/api/v1/access/ssh-profiles", json={**payload, "name": "Steal A"}).status_code
        == 409
    )
    assert len(admin_client.get("/api/v1/access/ssh-profiles").json()["items"]) == 2
    with env() as db:
        user = db.scalar(select(m.User).where(m.User.role == "admin"))
        assert service.resolve_profile(db, user, device_id)[1]["username"] == "switch-admin"
        assert service.resolve_profile(db, user, second_id)[1]["port"] == 2200
        owner_id = user.id
        assert all("secret" not in p.encrypted_ssh for p in db.scalars(select(m.UserSSHProfile)))
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    response = admin_client.post("/api/v1/access/sessions", json={"device_id": device_id})
    assert response.status_code == 201
    value = e.read(memory, "session", response.json()["id"])
    assert value["ssh_profile_id"] == first_id
    assert runtime.connection_data(value, device_id)[1]["password"] == "first-secret"
    assert admin_client.delete(f"/api/v1/access/ssh-profiles/{first_id}").status_code == 204
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": device_id}).status_code == 409
    replacement = admin_client.post("/api/v1/access/ssh-profiles", json={**payload, "name": "Replacement"})
    assert replacement.status_code == 201
    with pytest.raises(Exception) as exc:
        runtime.connection_data(value, device_id)
    assert exc.value.status_code == 409
    # The UNIQUE rule is enforced by the database as well as by the service lock.
    from sqlalchemy.exc import IntegrityError

    with env() as db:
        db.add(m.AccessGroupDevice(group_id=b["id"], owner_id=owner_id, device_id=device_id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    selection = admin_client.get("/api/v1/access/device-selection").json()
    assert selection["ids"] == [] and selection["skipped"] == 2
    selection = admin_client.get("/api/v1/access/device-selection", params={"group_id": a["id"]}).json()
    assert selection["ids"] == [device_id] and selection["skipped"] == 1
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "fixture-long-password"}
    )
    assert admin_client.get("/api/v1/access/ssh-profiles").json()["items"] == []
    assert (
        admin_client.put(f"/api/v1/access/ssh-profiles/{replacement.json()['id']}", json=payload).status_code
        == 404
    )
    assert admin_client.delete(f"/api/v1/access/ssh-profiles/{replacement.json()['id']}").status_code == 404
    assert (
        admin_client.post("/api/v1/access/ssh-profiles", json={**payload, "name": "Cross owner"}).status_code
        == 422
    )
    # Personal grouping of another user's device does not share that user's credentials.
    assert (
        admin_client.post(
            "/api/v1/access/groups", json={"name": "Personal A", "device_ids": [device_id]}
        ).status_code
        == 201
    )


def test_appearance_defaults_and_isolation(admin_client, target, env):
    device_id, user_id = target
    with env() as db:
        owner = db.scalar(select(m.User).where(m.User.role == "admin"))
        db.add(m.UserWorkspace(user_id=owner.id, preferences={"palette": "amber", "timezone": "UTC"}))
        db.commit()
    assert admin_client.get("/api/v1/access/preferences").json()["design"] == "atlas"
    for design in ("atlas", "orbit", "terminal", "panorama", "focus"):
        result = admin_client.put("/api/v1/access/preferences", json={"design": design, "palette": "amber"})
        assert result.status_code == 200 and result.json()["design"] == design
    assert admin_client.put("/api/v1/access/preferences", json={"design": "arbitrary-css"}).status_code == 422
    assert (
        admin_client.put("/api/v1/access/preferences", json={"palette": "arbitrary-color"}).status_code == 422
    )
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.UserWorkspace)) == 1
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "fixture-long-password"}
    )
    prefs = admin_client.get("/api/v1/access/preferences").json()
    assert prefs["palette"] == "cobalt" and prefs["design"] == "atlas"


def test_batch_tab_draft_is_encrypted_bounded_and_never_executes(admin_client, target, env, monkeypatch):
    device_id, other_user = target
    assert profile(admin_client).status_code == 201
    memory = EphemeralRedis()
    monkeypatch.setattr(e, "redis_client", lambda: memory)
    payload = {"device_ids": [device_id], "command": "show version draft-secret-marker", "timeout": 45}
    result = admin_client.post("/api/v1/access/batch-drafts", json=payload)
    assert result.status_code == 201
    id = result.json()["id"]
    assert "draft-secret-marker" not in memory.data[e.key("draft", id)]
    assert memory.ttls[e.key("draft", id)] == 600 and not memory.queue
    saved = admin_client.get("/api/v1/access/batch-drafts/" + id).json()
    assert saved["command"] == payload["command"] and saved["targets"][0]["device_id"] == device_id
    assert "auth_hash" not in saved and "password" not in saved
    for _ in range(15):
        assert admin_client.post("/api/v1/access/batch-drafts", json=payload).status_code == 201
    assert admin_client.post("/api/v1/access/batch-drafts", json=payload).status_code == 429
    assert admin_client.delete("/api/v1/access/batch-drafts/" + id).status_code == 204
    assert admin_client.get("/api/v1/access/batch-drafts/" + id).status_code == 404
    assert admin_client.post("/api/v1/access/batch-drafts", json=payload).status_code == 201
    assert not memory.queue
    retained_id = next(iter(memory.zsets.values()))
    retained_id = next(iter(retained_id))
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "fixture-long-password"}
    )
    assert admin_client.get("/api/v1/access/batch-drafts/" + retained_id).status_code == 404
    assert admin_client.delete("/api/v1/access/batch-drafts/" + retained_id).status_code == 404
    assert admin_client.post("/api/v1/access/batch-drafts", json=payload).status_code == 403
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
