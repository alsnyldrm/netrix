"""Bounded, read-only tests of saved or unsaved integration settings."""

import asyncio
import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from requests import exceptions as requests_errors
from winrm.exceptions import InvalidCredentialsError

from .. import models as m
from ..core import now, session_factory
from ..discovery import interactive_tests
from ..identity.security import audit, decrypt, encrypt
from ..services import get
from . import adapters

KIND = "test_integration"
TTL = 120
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="integration-test")


def key(job_id):
    return f"netrix:integration-test:{job_id}"


def start(db, payload, user, integration_id=None):
    saved = get(db, m.Integration, integration_id) if integration_id else None
    target_changed = saved and (saved.host, saved.port, saved.kind) != (
        payload.host,
        payload.port,
        payload.kind,
    )
    if not saved or target_changed or payload.username or payload.password:
        if not payload.username or not payload.password:
            raise HTTPException(422, "Kullanıcı ve parola birlikte gerekli; sunucu değişiminde yeniden girin")
        secret = {"username": payload.username, "password": payload.password}
    else:
        secret = json.loads(decrypt(saved.encrypted_secret))
    config = payload.model_dump(exclude={"username", "password"})
    job_id = str(uuid4())
    client = interactive_tests.redis_client()

    def create():
        job = m.Job(
            id=job_id,
            kind=KIND,
            target_id=integration_id or job_id,
            active_key=f"{KIND}:{job_id}",
            requested_by=user.id,
            total=1,
            result={"integration_kind": payload.kind, "target": payload.host, "port": payload.port},
        )
        db.add(job)
        db.flush()
        client.set(key(job_id), encrypt(json.dumps({"config": config, "secret": secret})), ex=TTL)
        audit(db, user, "integration_test", "jobs", job.id, "Entegrasyon bağlantı testi başlatıldı")
        return job

    try:
        return interactive_tests.start(db, KIND, integration_id or job_id, user, create=create)
    except Exception:
        # A rejected admission must not leave a job or a usable draft behind.
        db.rollback()
        with suppress(Exception):
            client.set(key(job_id), "", ex=1)
        raise


def probe(config, secret):
    if config.kind == "windows_dhcp":
        adapters.windows_dhcp(
            config,
            secret,
            point=True,
            script="""$ErrorActionPreference = 'Stop'
Import-Module DhcpServer -ErrorAction Stop
Get-DhcpServerv4Scope -ErrorAction Stop | Select-Object -First 1 | Out-Null
'[]'
""",
        )
        return "WinRM HTTPS bağlantısı, kullanıcı doğrulaması ve DHCP kapsam okuması başarılı."
    from pyVim.connect import Disconnect
    from pyVmomi import vim

    si = adapters.connect_vcenter(config, secret)
    view = None
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        # Reading one visible VM is enough for a connection test; no inventory import.
        _ = view.view[:1]
        return "vCenter HTTPS bağlantısı, kullanıcı doğrulaması ve envanter erişimi başarılı."
    finally:
        if view is not None:
            with suppress(Exception):
                view.Destroy()
        Disconnect(si)


def failure(exc):
    from pyVmomi import vim

    if isinstance(exc, (TimeoutError, requests_errors.Timeout)):
        return (
            "timeout",
            "Bağlantı zaman aşımına uğradı. Sunucuya ağ erişimini ve bağlantı portunu kontrol edin.",
        )
    if isinstance(exc, (ssl.SSLError, requests_errors.SSLError)):
        return (
            "tls_failed",
            "TLS sertifikası doğrulanamadı. Sunucu adını, sertifika tarihini ve CA güven zincirini kontrol edin.",
        )
    if isinstance(exc, (InvalidCredentialsError, vim.fault.InvalidLogin)):
        return (
            "authentication_failed",
            "Kullanıcı adı veya parola doğrulanamadı. Hesap bilgilerini kontrol edin.",
        )
    if isinstance(exc, vim.fault.NoPermission):
        return "permission_denied", "Kullanıcı doğrulandı; vCenter envanter okuma yetkisi yetersiz."
    return (
        "connection_failed",
        "Bağlantı testi başarısız. Sunucu, port, kullanıcı/parola ve WinRM/DHCP veya vCenter okuma yetkilerini kontrol edin.",
    )


async def execute(job_id):
    from ..worker import Cancelled

    client = interactive_tests.redis_client()
    started = time.monotonic()
    try:
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
        encrypted = client.get(key(job_id))
        if not encrypted:
            result = {
                "success": False,
                "error_code": "expired",
                "message": "Test bilgilerinin süresi doldu. Bağlantıyı yeniden test edin.",
            }
        else:
            value = json.loads(decrypt(encrypted))
            try:
                async with asyncio.timeout(60):
                    message = await asyncio.get_running_loop().run_in_executor(
                        POOL,
                        probe,
                        SimpleNamespace(**value["config"]),
                        value["secret"],
                    )
                result = {"success": True, "message": message}
            except Exception as exc:
                code, message = failure(exc)
                result = {"success": False, "error_code": code, "message": message}
        result.update(duration_ms=round((time.monotonic() - started) * 1000), checked_at=now().isoformat())
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            job.progress = job.total = 1
            db.commit()
        return result
    finally:
        client.set(key(job_id), "", ex=1)
