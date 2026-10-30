import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import asyncssh
import pytest
from netrix import models as m
from netrix.configuration import fortios
from netrix.configuration.validation import MAX_CONFIG_BYTES, BackupError, validate_fortios_backup
from netrix.core import settings
from netrix.discovery import protocols
from netrix.identity.security import decrypt, encrypt
from netrix.worker import execute
from sqlalchemy import func, select

NATIVE = '#config-version=FG600F-7.4.4-FW-build2662-240514:opmode=0:vdom=0:user=fixture\n#conf_file_ver=12\nconfig system global\n    set hostname "fixture"\nend\nconfig system admin\n    edit "fixture"\n        set password ENC FIXTURE-SECRET\n    next\nend\n'


def install_ssh(monkeypatch, content=NATIVE.encode(), error=None):
    calls, paths = [], []
    connection = object()

    @asynccontextmanager
    async def connect(host, **kwargs):
        calls.append((host, kwargs))
        yield connection

    async def scp(source, destination, **kwargs):
        assert source[1] == "sys_config"
        if calls:
            assert source[0] is connection
        assert kwargs["preserve"] is False and kwargs["recurse"] is False
        path = Path(destination)
        paths.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        path.write_bytes(content)
        if error:
            raise error
        kwargs["progress_handler"](b"sys_config", bytes(path), len(content), len(content))

    monkeypatch.setattr(protocols.asyncssh, "connect", connect)
    monkeypatch.setattr(fortios.asyncssh, "scp", scp)
    return calls, paths


@pytest.mark.parametrize("trust", [False, True])
async def test_native_scp_backup_preserves_content_host_policy_and_cleans_temp(env, monkeypatch, trust):
    calls, paths = install_ssh(monkeypatch)
    device = SimpleNamespace(
        adapter="fortios", management_ip="192.0.2.1", config_port=2222, ssh_trust_host_key=trust
    )
    assert (
        await protocols.fetch_config(device, {"username": "fixture", "password": "fixture-password"})
        == NATIVE
    )
    assert calls[0][0] == device.management_ip
    options = calls[0][1]
    assert options["port"] == 2222 and options["client_keys"] == []
    assert options["known_hosts"] == (None if trust else settings().known_hosts)
    assert not paths[0].parent.exists()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"config system global\nend\n--More--",
        b"Command fail. Return code -61",
        NATIVE.encode()[:-4],
        b"\xff",
        NATIVE.encode() + b"--More--",
    ],
)
async def test_partial_cli_errors_invalid_encoding_never_become_backups(monkeypatch, content):
    _, paths = install_ssh(monkeypatch, content)
    with pytest.raises(BackupError) as error:
        await fortios.fetch_fortios_backup(object())
    assert error.value.code == "invalid_fortios"
    assert not paths[0].parent.exists()


async def test_scp_failure_is_sanitized_and_temporary_plaintext_removed(monkeypatch):
    _, paths = install_ssh(monkeypatch, error=asyncssh.SFTPFailure("password=DO-NOT-LEAK"))
    with pytest.raises(BackupError) as error:
        await fortios.fetch_fortios_backup(object())
    assert error.value.code == "scp_failed" and "DO-NOT-LEAK" not in str(error.value)
    assert not paths[0].parent.exists()


async def test_oversized_transfer_aborts_on_first_block_and_cleans_up(monkeypatch):
    paths = []

    async def scp(source, destination, **kwargs):
        paths.append(Path(destination))
        paths[-1].write_bytes(b"x" * 64)
        kwargs["progress_handler"](b"sys_config", b"local", 64, MAX_CONFIG_BYTES + 1)
        raise AssertionError("Must stop after first block")

    monkeypatch.setattr(fortios.asyncssh, "scp", scp)
    with pytest.raises(BackupError) as error:
        await fortios.fetch_fortios_backup(object())
    assert error.value.code == "too_large"
    assert not paths[0].parent.exists()


async def test_cancelled_transfer_removes_partial_plaintext(monkeypatch):
    started = asyncio.Event()
    paths = []

    async def scp(source, destination, **kwargs):
        paths.append(Path(destination))
        paths[-1].write_text("partial private config")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(fortios.asyncssh, "scp", scp)
    task = asyncio.create_task(fortios.fetch_fortios_backup(object()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not paths[0].parent.exists()


def test_multivdom_header_is_not_treated_as_partial():
    validate_fortios_backup(
        NATIVE.replace("vdom=0", "vdom=1") + "config vdom\n    edit root\n    next\nend\n"
    )


async def test_rest_backup_rejected_before_any_connection():
    with pytest.raises(BackupError) as error:
        await protocols.fetch_config(SimpleNamespace(adapter="rest"), {"token": "DO-NOT-LEAK"})
    assert error.value.code == "ssh_required"


def make_device(client, inventory, protocol="ssh"):
    profile = client.post(
        "/api/v1/credentials",
        json={
            "name": "Backup " + protocol,
            "protocol": protocol,
            "secret": {
                "username": "fixture",
                "password": "fixture-password",
                "token": "fixture-token",
                "auth_key": "fixture-auth",
                "priv_key": "fixture-priv",
                "community": "fixture-community",
            },
        },
    ).json()
    payload = {
        "name": "Backup device",
        "management_ip": "192.0.2.1",
        "vrf_id": inventory["vrf"]["id"],
        "adapter": "rest" if protocol == "rest" else "fortios",
    }
    payload["snmp_credential_id" if protocol.startswith("snmp") else "config_credential_id"] = profile["id"]
    response = client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json(), profile


@pytest.mark.parametrize("protocol", ["rest", "snmpv3", "snmpv2c"])
@pytest.mark.parametrize("kind", ["backup", "compare"])
async def test_api_and_preexisting_jobs_require_ssh(admin_client, inventory, env, protocol, kind):
    c = admin_client
    device, _ = make_device(c, inventory, protocol)
    with env() as db:
        old = m.Job(kind="backup", target_id=device["id"], status="succeeded")
        db.add(old)
        db.flush()
        snapshot = m.Snapshot(
            device_id=device["id"],
            job_id=old.id,
            fingerprint="old",
            encrypted_content=encrypt(NATIVE),
            size_bytes=len(NATIVE),
        )
        db.add(snapshot)
        db.commit()
        snapshot_id = snapshot.id
    response = (
        c.post("/api/v1/jobs", json={"kind": kind, "target_id": device["id"]})
        if kind == "backup"
        else c.post(f"/api/v1/snapshots/{snapshot_id}/compare-live")
    )
    assert response.status_code == 422 and "yalnızca SSH" in response.text
    with env() as db:
        # A job queued before the upgrade must be rejected again by the worker.
        queued = m.Job(
            kind=kind,
            target_id=device["id"],
            status="queued",
            result={"base_snapshot_id": snapshot_id} if kind == "compare" else {},
        )
        db.add(queued)
        db.commit()
        job_id = queued.id
    await execute(job_id)
    result = c.get("/api/v1/jobs/" + job_id).json()
    assert result["status"] == "failed" and "yalnızca SSH" in result["error"]
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 1


async def test_worker_native_export_encrypted_and_comparison_uses_same_source(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    device, _ = make_device(c, inventory)
    calls, paths = install_ssh(monkeypatch)
    job = c.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()
    await execute(job["id"])
    assert c.get("/api/v1/jobs/" + job["id"]).json()["status"] == "succeeded"
    snapshot = c.get("/api/v1/snapshots").json()["items"][0]
    with env() as db:
        stored = db.get(m.Snapshot, snapshot["id"])
        assert (
            decrypt(stored.encrypted_content) == NATIVE and "FIXTURE-SECRET" not in stored.encrypted_content
        )
    assert "FIXTURE-SECRET" not in c.get(f"/api/v1/snapshots/{snapshot['id']}/content").text
    job = c.post(f"/api/v1/snapshots/{snapshot['id']}/compare-live").json()
    await execute(job["id"])
    result = c.get("/api/v1/backup-comparisons/" + job["id"]).json()
    assert result["status"] == "succeeded" and result["result"]["changed"] is False
    assert len(calls) == 2 and all(not p.exists() for p in paths)


async def test_invalid_export_is_failed_without_snapshot(admin_client, inventory, env, monkeypatch):
    c = admin_client
    device, _ = make_device(c, inventory)
    install_ssh(monkeypatch, b"config system global\n--More--")
    job = c.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()
    await execute(job["id"])
    assert c.get("/api/v1/jobs/" + job["id"]).json()["status"] == "failed"
    assert c.get("/api/v1/snapshots").json()["total"] == 0
    assert c.get("/api/v1/devices/" + device["id"]).json()["last_backup_at"] is None


def test_partial_legacy_backup_cannot_start_live_comparison(admin_client, inventory, env):
    c = admin_client
    device, _ = make_device(c, inventory)
    with env() as db:
        job = m.Job(kind="backup", target_id=device["id"], status="succeeded")
        db.add(job)
        db.flush()
        snapshot = m.Snapshot(
            device_id=device["id"],
            job_id=job.id,
            fingerprint="legacy",
            encrypted_content=encrypt("config system global\n--More--"),
            size_bytes=30,
        )
        db.add(snapshot)
        db.commit()
        snapshot_id = snapshot.id
    result = c.post(f"/api/v1/snapshots/{snapshot_id}/compare-live")
    assert result.status_code == 422 and "yeni bir yedek" in result.text
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "compare")) == 0
        assert db.get(m.Snapshot, snapshot_id) is not None


async def test_backup_settings_change_while_reading_discards_result(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    device, profile = make_device(c, inventory)

    async def fetch(device, secret):
        with env() as db:
            current = db.get(m.Device, device.id)
            current.config_port = 2222
            db.commit()
        return NATIVE

    monkeypatch.setattr("netrix.worker.fetch_config", fetch)
    job = c.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()
    await execute(job["id"])
    result = c.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "failed" and "bağlantı ayarı değişti" in result["error"]
    assert c.get("/api/v1/snapshots").json()["total"] == 0


def test_snmp_profile_cannot_be_used_as_backup_credential(admin_client, inventory, env):
    c = admin_client
    device, profile = make_device(c, inventory, "snmpv3")
    with env() as db:
        db.get(m.Device, device["id"]).config_credential_id = profile["id"]
        db.commit()
    result = c.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]})
    assert result.status_code == 422 and "yalnızca SSH" in result.text
