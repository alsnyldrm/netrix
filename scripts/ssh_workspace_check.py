"""Real AsyncSSH + Redis + WebSocket integration on loopback only; no device access.

Run with a disposable Redis URL (NETRIX_SSH_TEST_REDIS, default localhost:16441).
The script refuses any non-loopback Redis address and uses a temporary SQLite DB.
"""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import asyncssh
import httpx
import uvicorn
import websockets
from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-ssh-integration-")
redis_url = os.environ.get("NETRIX_SSH_TEST_REDIS", "redis://127.0.0.1:16441/0")
assert urlparse(redis_url).hostname in ("127.0.0.1", "localhost", "::1"), "Loopback test Redis required"
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "test.db"),
    NETRIX_REDIS_URL=redis_url,
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="isolated-ssh-test-setup-token",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8242",
    NETRIX_SECURE_COOKIES="false",
    NETRIX_KNOWN_HOSTS=str(Path(fixture.name) / "known_hosts"),
    NETRIX_FIRMWARE_DIRECTORY=str(Path(fixture.name) / "firmware"),
)
from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.access import ephemeral as e  # noqa: E402
from netrix.access import runtime  # noqa: E402
from netrix.core import Base, engine, session_factory  # noqa: E402
from netrix.identity.security import encrypt, issue_session  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import select  # noqa: E402

Base.metadata.create_all(engine())
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    user = m.User(
        email="loopback@example.test",
        display_name="Loopback",
        role="admin",
        ssh_access=True,
        password_hash="unused",
    )
    vrf = m.VRF(name="Loopback")
    credential = m.Credential(name="Fixture", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add_all([user, vrf, credential])
    db.flush()
    scope = m.Scope(name="Loopback", cidr="127.0.0.0/8", vrf_id=vrf.id, credential_id=credential.id)
    db.add(scope)
    db.flush()
    device = m.Device(
        name="Loopback switch",
        management_ip="127.0.0.1",
        vrf_id=vrf.id,
        discovery_scope_id=scope.id,
        adapter="aruba_2900",
        kind="switch",
    )
    db.add(device)
    db.flush()
    token = issue_session(db, user)
    db.commit()
    device_id, user_id = device.id, user.id

commands = []
active = 0
peak = 0


class SSHServer(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "fixture" and password == "fixture-password"


async def shell(process):
    global active, peak
    active += 1
    peak = max(active, peak)
    try:
        process.stdout.write("Fixture switch\r\nSW-01# ")
        while True:
            try:
                line = await process.stdin.readline()
            except asyncssh.TerminalSizeChanged:
                continue
            if not line:
                break
            # Model a CLI's Ctrl-U line clearing before the logout command.
            line = line.split("\x15")[-1].strip()
            commands.append(line)
            if line == "exit":
                break
            if line == "hang":
                await asyncio.sleep(20)
            if line == "bad-command":
                process.stdout.write("% Invalid input\r\nSW-01# ")
            else:
                process.stdout.write(f"RESULT:{line}\r\nSW-01# ")
    except (asyncssh.Error, BrokenPipeError):
        pass
    finally:
        active -= 1
        process.exit(0)


async def until(ws, fragment):
    async with asyncio.timeout(8):
        output = ""
        while fragment not in output:
            message = json.loads(await ws.recv())
            if message["type"] == "output":
                output += message["data"]
        return output


async def check():
    client = Redis.from_url(redis_url, decode_responses=True)
    # Never flush any Redis: only remove this isolated test's NETRIX SSH namespace.
    assert not [k async for k in client.scan_iter("netrix:*")], "Redis must be empty and disposable"
    hostkey = asyncssh.generate_private_key("ssh-ed25519")
    ssh = await asyncssh.create_server(
        SSHServer, "127.0.0.1", 0, server_host_keys=[hostkey], process_factory=shell, line_editor=False
    )
    port = ssh.get_port()
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=8242, log_level="error", access_log=False)
    )
    server_task = asyncio.create_task(server.serve())
    await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=120)
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8242",
            cookies={"netrix_session": token},
            headers={"X-Netrix-Request": "1"},
        ) as api:
            group = await api.post(
                "/api/v1/access/groups", json={"name": "Loopback group", "device_ids": [device_id]}
            )
            assert group.status_code == 201, group.text
            profile = {
                "name": "Loopback SSH",
                "group_ids": [group.json()["id"]],
                "username": "fixture",
                "password": "fixture-password",
                "port": port,
                "initial_command": "no page",
                "connect_timeout": 3,
            }
            saved = await api.post("/api/v1/access/ssh-profiles", json=profile)
            assert saved.status_code == 201, saved.text
            profile_id = saved.json()["id"]
            # Default host-key policy fails closed before sending a command.
            Path(os.environ["NETRIX_KNOWN_HOSTS"]).write_text("")
            response = await api.post("/api/v1/access/sessions", json={"device_id": device_id})
            id = response.json()["id"]
            await runtime.execute(client, "session", id)
            result = (await api.get("/api/v1/access/sessions/" + id)).json()
            assert result["status"] == "failed" and "host anahtarı" in result["error"], result
            assert not commands
            Path(os.environ["NETRIX_KNOWN_HOSTS"]).write_text(
                f"[127.0.0.1]:{port} " + hostkey.export_public_key().decode()
            )
            response = await api.post("/api/v1/access/sessions", json={"device_id": device_id})
            id = response.json()["id"]
            job = asyncio.create_task(runtime.execute(client, "session", id))
            url = f"ws://127.0.0.1:8242/api/v1/access/sessions/{id}/ws"
            async with websockets.connect(
                url, origin="http://127.0.0.1:8242", additional_headers={"Cookie": "netrix_session=" + token}
            ) as ws:
                await until(ws, "RESULT:no page")
                await ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
                await ws.send(json.dumps({"type": "input", "data": "show version\n"}))
                assert "RESULT:show version" in await until(ws, "RESULT:show version")
                assert commands.count("no page") == 1
                stream = await client.xrange(e.key("out", id))
                assert all("RESULT" not in fields["data"] for _, fields in stream)
                try:
                    async with websockets.connect(
                        url,
                        origin="https://untrusted.example",
                        additional_headers={"Cookie": "netrix_session=" + token},
                    ):
                        raise AssertionError("Cross-origin WebSocket accepted")
                except websockets.InvalidStatus:
                    pass
                async with websockets.connect(
                    url,
                    origin="http://127.0.0.1:8242",
                    additional_headers={"Cookie": "netrix_session=" + token},
                ) as other:
                    await until(other, "RESULT:show version")
                    assert (await api.delete("/api/v1/access/sessions/" + id)).status_code == 204
                    await asyncio.wait_for(job, 5)
                    assert commands.count("exit") == 1 and active == 0, commands
                assert commands.count("show version") == 1
            count = len(commands)
            await runtime.execute(client, "session", id)
            assert len(commands) == count, "Duplicate delivery re-executed"
            # An admin without an explicit SSH role loses a live connection too.
            response = await api.post("/api/v1/access/sessions", json={"device_id": device_id})
            revoked_id = response.json()["id"]
            revoked_job = asyncio.create_task(runtime.execute(client, "session", revoked_id))
            async with websockets.connect(
                f"ws://127.0.0.1:8242/api/v1/access/sessions/{revoked_id}/ws",
                origin="http://127.0.0.1:8242",
                additional_headers={"Cookie": "netrix_session=" + token},
            ) as revoked_ws:
                await until(revoked_ws, "RESULT:no page")
                with session_factory()() as db:
                    db.get(m.User, user_id).ssh_access = False
                    db.commit()
                assert (await api.get("/api/v1/access/ssh-profiles")).status_code == 403
                await asyncio.wait_for(revoked_job, 12)
            assert commands.count("exit") == 2 and active == 0
            with session_factory()() as db:
                db.get(m.User, user_id).ssh_access = True
                db.commit()
            await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=120)
            # PTY batch keeps startup and command in one shell; returns per-device CLI failure.
            for command, expected in (
                ("show system", "succeeded"),
                ("bad-command", "failed"),
                ("hang", "failed"),
            ):
                await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=120)
                response = await api.post(
                    "/api/v1/access/batches",
                    json={"device_ids": [device_id], "command": command, "timeout": 5},
                )
                assert response.status_code == 202, response.text
                batch_id = response.json()["id"]
                await runtime.execute(client, "batch", batch_id)
                result = (await api.get("/api/v1/access/batches/" + batch_id)).json()
                assert result["targets"][0]["status"] == expected, result
                if command == "hang":
                    assert "zaman aşımı" in result["targets"][0]["output"].lower()
                before = commands.count(command)
                await runtime.execute(client, "batch", batch_id)
                assert commands.count(command) == before
            # Use the real one-minute minimum: output and viewer heartbeats must
            # not keep an idle SSH session alive. No clock overrides or device access.
            await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=120)
            response = await api.put(
                f"/api/v1/access/ssh-profiles/{profile_id}", json={**profile, "idle_timeout_minutes": 1}
            )
            assert response.status_code == 200, response.text
            response = await api.post("/api/v1/access/sessions", json={"device_id": device_id})
            assert response.status_code == 201 and response.json()["idle_timeout_minutes"] == 1
            idle_id = response.json()["id"]
            started = time.monotonic()
            idle_job = asyncio.create_task(runtime.execute(client, "session", idle_id))
            async with websockets.connect(
                f"ws://127.0.0.1:8242/api/v1/access/sessions/{idle_id}/ws",
                origin="http://127.0.0.1:8242",
                additional_headers={"Cookie": "netrix_session=" + token},
            ) as idle_ws:
                await until(idle_ws, "RESULT:no page")
                await asyncio.wait_for(idle_job, 65)
            assert 60 <= time.monotonic() - started < 66
            result = (await api.get("/api/v1/access/sessions/" + idle_id)).json()
            assert result["status"] == "closed" and "Hareketsizlik" in result["error"], result
            assert commands.count("exit") == 3 and active == 0, commands
            assert idle_id not in await client.zrange(e.PREFIX + "session:active", 0, -1)
            await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=120)
            # Password validation failure reveals no credential values.
            await api.put(
                f"/api/v1/access/ssh-profiles/{profile_id}",
                json={**profile, "password": "wrong-secret-marker"},
            )
            response = await api.post(
                "/api/v1/access/batches",
                json={"device_ids": [device_id], "command": "show system", "timeout": 5},
            )
            batch_id = response.json()["id"]
            await runtime.execute(client, "batch", batch_id)
            result = (await api.get("/api/v1/access/batches/" + batch_id)).json()
            assert result["targets"][0]["status"] == "failed"
            assert "wrong-secret-marker" not in json.dumps(result)
        with session_factory()() as db:
            assert not list(db.scalars(select(m.Job))), "Interactive SSH wrote durable jobs"
        print(
            json.dumps(
                {
                    "real_ssh": True,
                    "websocket": True,
                    "host_key": True,
                    "initial_command_once": True,
                    "batch_success_failure_timeout": True,
                    "no_replay": True,
                    "cross_origin_denied": True,
                    "wrong_password_denied": True,
                    "exit_on_close": True,
                    "real_idle_logout_60_seconds": True,
                    "admin_ssh_revocation_logs_out": True,
                }
            )
        )
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        ssh.close()
        await ssh.wait_closed()
        keys = [key async for key in client.scan_iter("netrix:*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


asyncio.run(check())
