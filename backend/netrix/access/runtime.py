"""Dedicated, bounded SSH worker in the existing NETRIX container. No replay/retry."""

import asyncio
import json
import logging
import re
import signal
import time

import asyncssh
from fastapi import HTTPException
from redis.asyncio import Redis

from .. import models as m
from ..core import now, session_factory, settings
from ..discovery.aruba import CLI_ERROR, terminal_text
from ..discovery.protocols import ssh_known_hosts
from . import ephemeral as e
from . import service as svc

OUTPUT_LIMIT = 65536
PROMPT = re.compile(r"(?m)^(?:[^\r\n]{1,160}[#$>]\s*|<[^\r\n<>]{1,120}>\s*|\[[^\r\n\[\]]{1,120}\]\s*)\Z")


class SessionEnded(Exception):
    pass


def connection_data(value, device_id):
    with session_factory()() as db:
        auth = db.get(m.AuthSession, value["auth_hash"])
        user = db.get(m.User, value["user_id"])
        if (
            not auth
            or auth.user_id != value["user_id"]
            or auth.expires_at <= now()
            or not user
            or not user.is_active
        ):
            raise HTTPException(403, "Oturum veya yetki sona erdi")
        device = svc.authorize_device(db, user, device_id)
        expected = value.get("ssh_profile_id")
        if "targets" in value:
            expected = next(
                (t.get("ssh_profile_id") for t in value["targets"] if t["device_id"] == device_id), None
            )
        _, profile = svc.resolve_profile(db, user, device_id, expected_id=expected)
        return device, profile


def connect(device, profile):
    keys = []
    if profile.get("private_key"):
        keys = [
            asyncssh.import_private_key(profile["private_key"], passphrase=profile.get("passphrase") or None)
        ]
    return asyncssh.connect(
        device.management_ip,
        port=profile["port"],
        username=profile["username"],
        password=profile.get("password") or None,
        client_keys=keys,
        agent_path=None,
        config=None,
        known_hosts=ssh_known_hosts(device),
        connect_timeout=profile["connect_timeout"],
        login_timeout=15,
        keepalive_interval=20,
        keepalive_count_max=3,
    )


def error_message(exc):
    if isinstance(exc, HTTPException):
        return exc.detail
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "Zaman aşımı; komut otomatik tekrarlanmadı. Sonucu cihazdan doğrulayın."
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return "SSH host anahtarı doğrulanamadı. Envanterdeki anahtar güven ayarını kontrol edin."
    if isinstance(exc, asyncssh.PermissionDenied):
        return "SSH kullanıcı doğrulaması reddedildi"
    if isinstance(exc, SessionEnded):
        return "İşlem iptal edildi veya bağlantı sona erdi"
    if isinstance(exc, ValueError):
        return "SSH anahtarı veya bağlantı ayarları geçersiz"
    return "SSH bağlantısı veya komut tamamlanamadı. Komut otomatik tekrarlanmadı."


async def state(client, kind, id, value, ttl=e.TTL):
    if kind == "batch":
        targets = value.get("targets", [])
        if targets:
            await client.hset(
                e.key("batch-targets", id), mapping={t["device_id"]: e.pack(t) for t in targets}
            )
            await client.expire(e.key("batch-targets", id), ttl)
        value = {**value, "targets": [{**t, "output": ""} for t in targets]}
    await client.set(e.key(kind, id), e.pack(value), ex=ttl)


async def target_state(client, id, target):
    # Persist only the changed device. Do not encrypt/rewrite accumulated output
    # from every earlier target on each progress update.
    await client.hset(e.key("batch-targets", id), target["device_id"], e.pack(target))
    await client.expire(e.key("batch-targets", id), e.TTL)


async def event(client, id, value):
    # 128 * 4KiB = at most 512KiB of recent text, encrypted before Redis persistence.
    await client.xadd(e.key("out", id), {"data": e.pack(value)}, maxlen=128, approximate=False)
    await client.expire(e.key("out", id), e.TTL)


async def shell_session(client, id, value):
    device, profile = await asyncio.to_thread(connection_data, value, value["device_id"])
    async with connect(device, profile) as connection:
        async with connection.create_process(
            term_type="xterm-256color", term_size=(value["cols"], value["rows"]), stderr=asyncssh.STDOUT
        ) as process:
            value["status"] = "connected"
            await state(client, "session", id, value)
            await event(client, id, {"type": "status", "status": "connected"})
            if profile.get("initial_command"):
                process.stdin.write(profile["initial_command"].replace("\r\n", "\n") + "\n")
            last_input = time.monotonic()

            async def output():
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        return
                    await event(client, id, {"type": "output", "data": chunk})

            async def incoming():
                nonlocal last_input
                cursor = "0-0"
                authorized_at = 0
                while True:
                    events = await client.xread({e.key("in", id): cursor}, count=32, block=500)
                    for _, messages in events:
                        for cursor, fields in messages:
                            data = e.unpack(fields["data"])
                            if data["type"] == "input":
                                # Bound DB reads while typing; watchdog also checks grants every 10s.
                                if time.monotonic() - authorized_at >= 2:
                                    await asyncio.to_thread(connection_data, value, value["device_id"])
                                    authorized_at = time.monotonic()
                                process.stdin.write(data["data"])
                                await process.stdin.drain()
                                last_input = time.monotonic()
                            elif data["type"] == "resize":
                                process.change_terminal_size(data["cols"], data["rows"])
                            await client.xdel(e.key("in", id), cursor)

            async def watchdog():
                checked = 0
                absent = time.monotonic()
                while True:
                    await asyncio.sleep(1)
                    stamp = time.monotonic()
                    if await client.get(e.key("viewer", id)):
                        absent = stamp
                    if (
                        await client.get(e.key("cancel", id))
                        or stamp - absent > 60
                        or stamp - last_input > 900
                        or time.time() - value["created"] > e.TTL
                    ):
                        raise SessionEnded()
                    if stamp - checked >= 10:
                        await asyncio.to_thread(connection_data, value, value["device_id"])
                        checked = stamp

            tasks = [asyncio.create_task(fn()) for fn in (output, incoming, watchdog)]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)


async def read_prompt(process):
    output = ""
    while True:
        chunk = await process.stdout.read(4096)
        if not chunk:
            raise SessionEnded()
        output += chunk
        if len(output.encode()) > OUTPUT_LIMIT:
            raise ValueError("output_limit")
        clean = terminal_text(output)
        if PROMPT.search(clean):
            return clean


async def run_command(device, profile, command):
    """One PTY for network CLI; Linux uses exec and its real exit status."""
    async with connect(device, profile) as connection:
        if device.adapter == "linux":
            full = (profile.get("initial_command", "") + "\n" + command).strip()
            async with connection.create_process(full, stderr=asyncssh.STDOUT) as process:
                output = ""
                while chunk := await process.stdout.read(4096):
                    output += chunk
                    if len(output.encode()) > OUTPUT_LIMIT:
                        raise ValueError("output_limit")
                await process.wait_closed()
                return output, process.exit_status == 0
        async with connection.create_process(
            term_type="vt100", term_size=(200, 40), stderr=asyncssh.STDOUT
        ) as process:
            await read_prompt(process)
            initial = profile.get("initial_command", "").strip()
            if initial:
                for line in initial.splitlines():
                    process.stdin.write(line + "\n")
                    output = await read_prompt(process)
                    if CLI_ERROR.search(output):
                        return output, False
            outputs = []
            for line in command.splitlines():
                if not line.strip():
                    continue
                process.stdin.write(line + "\n")
                output = await read_prompt(process)
                outputs.append(output)
                if len("\n".join(outputs).encode()) > OUTPUT_LIMIT:
                    raise ValueError("output_limit")
                if CLI_ERROR.search(output) or re.search(
                    r"(?im)(?:command fail|error:|syntax error|invalid input|not found)", output
                ):
                    return "\n".join(outputs), False
            return "\n".join(outputs), True


async def run_batch(client, id, value):
    semaphore = asyncio.Semaphore(4)
    writing = asyncio.Lock()
    value["status"] = "running"
    await state(client, "batch", id, value)

    async def one(target):
        async with semaphore:
            target["status"] = "running"
            async with writing:
                await target_state(client, id, target)
            try:
                if await client.get(e.key("cancel", id)):
                    raise SessionEnded()
                device, profile = await asyncio.to_thread(connection_data, value, target["device_id"])
                async with asyncio.timeout(value["timeout"]):
                    output, success = await run_command(device, profile, value["command"])
                async with writing:
                    used = sum(len(t.get("output", "").encode()) for t in value["targets"])
                    remaining = max(0, 2 * 1024 * 1024 - used)
                    if len(output.encode()) > remaining:
                        output = (
                            output.encode()[:remaining].decode(errors="ignore")
                            + "\n[Toplam çıktı sınırı: 2 MiB]"
                        )
                    target.update(status="succeeded" if success else "failed", output=output)
            except asyncio.CancelledError:
                target.update(
                    status="cancelled", output="İptal edildi; daha önce gönderilmiş komut geri alınamaz."
                )
                raise
            except Exception as exc:
                target.update(
                    status="failed",
                    output="Çıktı 64 KiB sınırını aştı; komut tekrarlanmadı"
                    if isinstance(exc, ValueError) and str(exc) == "output_limit"
                    else error_message(exc),
                )
            finally:
                async with writing:
                    await target_state(client, id, target)

    tasks = [asyncio.create_task(one(target)) for target in value["targets"]]
    checked = time.monotonic()
    revoked = False
    try:
        while any(not t.done() for t in tasks):
            await asyncio.sleep(0.25)
            if time.monotonic() - checked >= 5:
                try:
                    for target in value["targets"]:
                        if target["status"] == "running":
                            await asyncio.to_thread(connection_data, value, target["device_id"])
                except HTTPException:
                    revoked = True
                checked = time.monotonic()
            if revoked or await client.get(e.key("cancel", id)):
                for task in tasks:
                    task.cancel()
                break
        await asyncio.gather(*tasks, return_exceptions=True)
        value["status"] = "cancelled" if revoked or await client.get(e.key("cancel", id)) else "completed"
        if revoked:
            value["error"] = "Oturum veya cihaz erişim yetkisi sona erdi"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for target in value["targets"]:
            if target["status"] in ("queued", "running"):
                target.update(status="cancelled", output="İptal edildi; komut otomatik tekrarlanmadı.")


async def execute(client, kind, id):
    value = e.unpack(await client.get(e.key(kind, id)))
    if not value:
        return
    # A duplicate Redis delivery cannot execute a command twice, even after restart.
    if not await client.set(e.key("claimed", id), "1", nx=True, ex=e.TTL):
        return
    try:
        if await client.get(e.key("cancel", id)):
            raise SessionEnded()
        if kind == "session":
            await shell_session(client, id, value)
            value["status"] = "closed"
        else:
            await run_batch(client, id, value)
    except SessionEnded:
        value.update(status="cancelled", error="İşlem iptal edildi veya bağlantı sona erdi")
        for target in value.get("targets", []):
            if target["status"] in ("queued", "running"):
                target.update(status="cancelled", output="İptal edildi; komut gönderilmedi.")
    except asyncio.CancelledError:
        value.update(status="cancelled", error="SSH hizmeti durdu; komut otomatik tekrarlanmadı")
        raise
    except Exception as exc:
        value.update(status="failed", error=error_message(exc))
    finally:
        if kind == "session":
            await event(
                client, id, {"type": "status", "status": value["status"], "error": value.get("error", "")}
            )
            await client.delete(e.key("in", id))
            await client.expire(e.key("out", id), e.RESULT_TTL)
        value.pop("command", None)
        await state(client, kind, id, value, ttl=e.RESULT_TTL)
        await client.zrem(e.PREFIX + kind + ":active", id)


async def main():
    client = Redis.from_url(settings().redis_url, decode_responses=True, socket_connect_timeout=2)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    tasks = set()
    batch_tasks = set()
    heartbeat_at = 0
    try:
        # Interrupted operations are not replayed: only queued, unclaimed requests run.
        for kind in ("session", "batch"):
            for id in await client.zrange(e.PREFIX + kind + ":active", 0, -1):
                value = e.unpack(await client.get(e.key(kind, id)))
                if value and (value["status"] != "queued" or await client.get(e.key("claimed", id))):
                    value.update(status="failed", error="SSH hizmeti yeniden başladı; işlem tekrarlanmadı")
                    value.pop("command", None)
                    await state(client, kind, id, value, ttl=e.RESULT_TTL)
                    await client.zrem(e.PREFIX + kind + ":active", id)
        while not stop.is_set():
            if time.monotonic() - heartbeat_at >= 3:
                await client.set(e.PREFIX + "heartbeat", str(time.time()), ex=30)
                heartbeat_at = time.monotonic()
            if len(tasks) < 34:
                delivery = await client.blpop(e.PREFIX + "queue", timeout=1)
                if delivery:
                    item = delivery[1]
                    data = json.loads(item)
                    if await client.get(e.key("cancel", data["id"])):
                        await execute(client, data["kind"], data["id"])
                    elif data["kind"] == "batch" and len(batch_tasks) >= 2:
                        await client.rpush(e.PREFIX + "queue", item)
                        await asyncio.sleep(0.25)
                    else:
                        task = asyncio.create_task(execute(client, data["kind"], data["id"]))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                        if data["kind"] == "batch":
                            batch_tasks.add(task)
                            task.add_done_callback(batch_tasks.discard)
            await asyncio.sleep(0.05)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.delete(e.PREFIX + "heartbeat")
        await client.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logging.getLogger("netrix.ssh").error("SSH worker stopped: %s", type(exc).__name__)
        raise SystemExit(1) from None
