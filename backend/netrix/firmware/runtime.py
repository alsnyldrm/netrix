"""Dedicated bounded firmware worker and grant-only file services in the NETRIX container."""

import asyncio
import hashlib
import logging
import re
import signal
import time
from datetime import timedelta

import asyncssh
from sqlalchemy import or_, select

from .. import models as m
from ..configuration import baselines
from ..configuration.formatting import config_text
from ..configuration.validation import validate_cli_output
from ..core import now, redis_client, session_factory, settings
from ..discovery.protocols import fetch_config
from ..identity.permissions import is_admin
from ..identity.security import encrypt, secret_data
from ..services import publish
from . import adapters, history, transfers
from .limits import MAX_CONCURRENCY
from .service import connection_stamp, image_path, service_info, transfer_protocol, validate_device
from .versions import compare

log = logging.getLogger("netrix.firmware")
stop = False
verified_images = {}


def set_phase(id, phase, **values):
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, id)
        previous = row.phase
        row.phase, row.heartbeat_at = phase, now()
        if previous != phase or phase == "preflight" and not row.evidence.get("history_version"):
            row.evidence = {**row.evidence, "history_version": 1}
            history.add_event(db, row, kind="phase", title=history.PHASES.get(phase, phase), finished=True)
        for key, value in values.items():
            setattr(row, key, {**value, "history_version": 1} if key == "evidence" else value)
        db.commit()
    publish()


def check_cancelled(id):
    with session_factory()() as db:
        target = db.get(m.FirmwareTarget, id)
        return db.get(m.FirmwarePlan, target.plan_id).cancel_requested


def load(id):
    with session_factory()() as db:
        target = db.get(m.FirmwareTarget, id)
        plan = db.get(m.FirmwarePlan, target.plan_id)
        device = db.get(m.Device, target.device_id)
        image = db.get(m.FirmwareImage, target.image_id)
        profile = validate_device(db, device, image)
        if target.evidence["connection_stamp"] != connection_stamp(device, profile):
            raise ValueError("connection_changed")
        if not db.get(m.User, plan.requested_by) or not db.get(m.User, plan.requested_by).is_active:
            raise ValueError("actor_disabled")
        if not is_admin(db.get(m.User, plan.requested_by)):
            raise ValueError("actor_disabled")
        return target, plan, device, image, secret_data(profile)


def verify_file(image):
    path = image_path(image)
    stat = path.stat()
    key = (image.id, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if key not in verified_images:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != image.sha256 or digest != image.expected_sha256 or stat.st_size != image.size_bytes:
            raise ValueError("file_changed")
        if len(verified_images) > 32:
            verified_images.clear()
        verified_images[key] = True
    return path


async def backup(id, device, secret):
    data = config_text(await fetch_config(device, secret))
    validate_cli_output(data)
    with session_factory()() as db:
        target, current = db.get(m.FirmwareTarget, id), db.get(m.Device, device.id)
        job = m.Job(
            kind="firmware_backup",
            target_id=device.id,
            requested_by=db.get(m.FirmwarePlan, target.plan_id).requested_by,
            status="succeeded",
            finished_at=now(),
            result={"firmware_target_id": id},
        )
        db.add(job)
        db.flush()
        reference = baselines.base(db, current)
        fingerprint = baselines.fingerprint(data)
        snapshot = m.Snapshot(
            device_id=device.id,
            job_id=job.id,
            encrypted_content=encrypt(data),
            size_bytes=len(data.encode()),
            fingerprint=fingerprint,
            changed=bool(reference and reference.fingerprint != fingerprint),
        )
        db.add(snapshot)
        db.flush()
        if not current.base_snapshot_id:
            current.base_snapshot_id = snapshot.id
        current.last_backup_at, target.snapshot_id = now(), snapshot.id
        history.add_event(
            db,
            target,
            kind="backup",
            title="Konfigürasyon yedeği güvenle saklandı",
            status="succeeded",
            response=f"Yedek kaydı: {snapshot.id}\nBoyut: {snapshot.size_bytes} bayt\nİçerik şifreli saklanır; komut geçmişine eklenmez.",
            finished=True,
        )
        db.commit()
        return snapshot.id


async def verify_running(id, device, secret, image, bank, *, wait=True, recorder=None):
    deadline = time.monotonic() + (1200 if wait else 60)
    stable, version = 0, ""
    if wait:
        await asyncio.sleep(12)
    while time.monotonic() < deadline:
        try:
            options = {"recorder": recorder} if recorder else {}
            async with adapters.connect(device, secret, **options) as (_, cli):
                data = await adapters.inspect(cli, device)
            version = data["version"]
            if adapters.matches_version(image.version, version) and (
                image.family == "hp1950" or data["bank"] == bank
            ):
                stable += 1
                if stable >= (2 if wait else 1):
                    return version
            else:
                stable = 0
                if not wait:
                    raise ValueError("version_mismatch")
        except (asyncssh.Error, OSError, TimeoutError, adapters.FirmwareError):
            stable = 0
            if not wait:
                raise
        await asyncio.sleep(10)
    raise ValueError("reboot_timeout")


def image_progress(id, percent, *, transferred_bytes=None):
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, id)
        phase = "reconcile" if row.phase == "reconcile" else "image_verifying"
        changed = row.phase != phase or row.evidence.get("image_verification_percent") != percent
        row.phase, row.heartbeat_at = phase, now()
        row.evidence = {**row.evidence, "image_verification_percent": percent}
        if transferred_bytes is not None:
            row.transfer_bytes = transferred_bytes
        if changed:
            history.add_event(
                db,
                row,
                kind="phase",
                title="Cihazın imaj bütünlüğü doğrulanıyor",
                response=f"Cihazın SHA-256 doğrulaması: %{percent}"
                if percent is not None
                else "Dosya aktarımı tamamlandı; cihazın SHA-256 sonucu bekleniyor.",
                finished=True,
            )
        db.commit()
    if changed:
        publish()


async def verify_staged(id, target, device, secret, image, recorder):
    if (
        not target.snapshot_id
        or target.bank not in ("primary", "secondary")
        or target.bank == target.previous_bank
    ):
        raise ValueError("not_staged")
    # Preserve the local file, backup and connection guarantees even for read-only repair.
    await asyncio.to_thread(verify_file, image)
    with session_factory()() as db:
        snapshot = db.get(m.Snapshot, target.snapshot_id)
        if not snapshot or snapshot.device_id != target.device_id:
            raise ValueError("not_staged")
    async with adapters.connect(device, secret, recorder=recorder) as (_, cli):
        live = await adapters.inspect(cli, device)
        if live["bank"] != target.previous_bank or not adapters.matches_version(
            target.previous_version, live["version"]
        ):
            raise ValueError("connection_changed")

        async def progress(percent):
            await asyncio.to_thread(image_progress, id, percent)

        await adapters.wait_cx_image(cli, target.bank, image, progress)
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, id)
        row.evidence = {
            **row.evidence,
            "staged": True,
            "staged_at": now().isoformat(),
            "staged_version": image.version,
            "staged_sha256": image.sha256,
            "image_verification_percent": 100,
        }
        db.commit()
    finish(id, "staged")


async def execute(id):
    mutated = False
    try:
        target, plan, device, image, secret = load(id)
        recorder = history.Recorder(id, (secret.get("password", ""), secret.get("username", "")))
        if target.phase == "reconcile":
            if plan.mode == "stage" and image.family == "cx6100":
                await verify_staged(id, target, device, secret, image, recorder)
                return
            await recorder.note("Sonuç yeniden doğrulanıyor", kind="phase")
            version = await verify_running(
                id, device, secret, image, target.bank, wait=False, recorder=recorder
            )
            finish(id, "succeeded", verified_version=version)
            return
        if check_cancelled(id):
            finish(id, "cancelled")
            return
        set_phase(id, "preflight")
        path = await asyncio.to_thread(verify_file, image)
        if image.family in ("cx6100", "hp1950") and not service_info()["configured"]:
            raise ValueError("transfer_service")
        key = transfers.host_key()
        fingerprints = (key.get_fingerprint("sha256"), key.get_fingerprint("md5"))
        async with adapters.connect(device, secret, key_fingerprints=fingerprints, recorder=recorder) as (
            connection,
            cli,
        ):
            live = await adapters.inspect(cli, device)
            transfer_started = False

            async def verify_progress(percent):
                await asyncio.to_thread(
                    image_progress,
                    id,
                    percent,
                    transferred_bytes=image.size_bytes if transfer_started else None,
                )

            if (
                image.family == "aos_s"
                and image.version.split(".")[0].upper() != live["version"].split(".")[0].upper()
            ):
                raise ValueError("image_family")
            if image.family == "hp1950":
                release = re.search(r"(?:R|Release\s*)(\d{4})", live["version"], re.I)
                if not release or image.version.startswith("R51") != release[1].startswith("51"):
                    raise ValueError("image_family")
            if plan.mode != "check":
                relation = compare(live["version"], image.version)
                if relation is None:
                    raise adapters.FirmwareError("version")
                if relation >= 0:
                    finish(id, "succeeded", verified_version=live["version"], skipped=True)
                    return
            prepare_sftp = False
            if image.family == "aos_s" and plan.mode != "activate":
                try:
                    await adapters.probe_sftp(connection)
                except adapters.FirmwareError:
                    if plan.mode == "check" or not plan.steps[target.stage].get("allow_enable_sftp"):
                        raise
                    prepare_sftp = True
            if plan.mode == "activate":
                if not target.snapshot_id or not target.evidence.get("staged"):
                    raise ValueError("not_staged")
                if not adapters.matches_version(target.previous_version, live["version"]):
                    raise ValueError("connection_changed")
                if image.family != "hp1950" and (
                    live["bank"] == target.bank
                    or not adapters.bank_contains(live["banks"], target.bank, image.version)
                ):
                    raise adapters.FirmwareError("image")
                bank = target.bank
            else:
                bank = (
                    "main"
                    if image.family == "hp1950"
                    else "secondary"
                    if live["bank"] == "primary"
                    else "primary"
                )
                evidence = {
                    **target.evidence,
                    "preflight_at": now().isoformat(),
                    "staged": False,
                    "protocol": transfer_protocol(image.family),
                }
                set_phase(
                    id,
                    "preflight",
                    bank=bank,
                    previous_bank=live["bank"],
                    previous_version=live["version"],
                    evidence=evidence,
                )
                if plan.mode == "check":
                    finish(id, "checked")
                    return
                if check_cancelled(id):
                    finish(id, "cancelled")
                    return
                set_phase(id, "backup")
                await backup(id, device, secret)
                load(id)  # Revalidate connection/permissions immediately before device writes.
                if check_cancelled(id):
                    finish(id, "cancelled")
                    return
                reused = False
                current = await adapters.inspect(cli, device)
                relation = compare(current["version"], image.version)
                if relation is not None and relation >= 0:
                    finish(id, "succeeded", verified_version=current["version"], skipped=True)
                    return
                if current["bank"] != live["bank"] or not adapters.matches_version(
                    live["version"], current["version"]
                ):
                    raise ValueError("connection_changed")
                if image.family == "cx6100":
                    # Read again after backup: another administrator may have
                    # changed the running image or the inactive area meanwhile.
                    if (
                        adapters.bank_contains(current["banks"], bank, image.version)
                        and adapters.cx_image_progress(current["banks"], bank) is not None
                    ):
                        await adapters.wait_cx_image(cli, bank, image, verify_progress)
                        reused = True
                    else:
                        reused = bool(image.sha256) and adapters.cx_image_matches(
                            current["banks"], bank, image
                        )
                    if check_cancelled(id):
                        finish(id, "cancelled")
                        return
                if not reused:
                    set_phase(id, "transferring")
                    # Persist the unsafe boundary BEFORE sending any mutation to the device.
                    mutated = True
                    if prepare_sftp:
                        await adapters.enable_sftp(cli)
                        await adapters.probe_sftp(connection)
                    username, password, filename = transfers.grant(id, transfer_protocol(image.family))
                    recorder.secrets.extend((username, password, filename))
                    await recorder.note(
                        "Dosya aktarımı başladı",
                        f"Yöntem: {transfer_protocol(image.family)}\nDosya: {image.original_name}\nBoyut: {image.size_bytes} bayt\nHedef yazılım alanı: {bank}\n"
                        + (
                            f"SFTP ile /os/{bank} yoluna yazılıyor."
                            if image.family == "aos_s"
                            else "Cihaz dosyayı NETRIX sunucusundan çekiyor."
                        ),
                    )
                    last = 0.0

                    def progress(size):
                        nonlocal last
                        if time.monotonic() - last > 2:
                            transfers.record_bytes(id, size)
                            last = time.monotonic()

                    transfer_started = True
                    await adapters.stage(
                        connection,
                        cli,
                        device,
                        image,
                        bank,
                        path,
                        {"username": username, "password": password, "filename": filename},
                        progress,
                        verify_progress,
                    )
                    transfers.revoke(id)
                with session_factory()() as db:
                    row = db.get(m.FirmwareTarget, id)
                    row.evidence = {
                        **row.evidence,
                        "staged": True,
                        "staged_at": now().isoformat(),
                        "transfer_reused": reused,
                        **(
                            {
                                "staged_version": image.version,
                                "staged_sha256": image.sha256,
                                "image_verification_percent": 100,
                            }
                            if image.family == "cx6100"
                            else {}
                        ),
                    }
                    row.transfer_bytes = 0 if reused else image.size_bytes
                    history.add_event(
                        db,
                        row,
                        kind="transfer",
                        title="Mevcut imaj yeniden kullanıldı"
                        if reused
                        else "İmaj hedef yazılım alanında doğrulandı",
                        status="succeeded",
                        response=f"Dosya: {image.original_name}\nSürüm: {image.version}\nYazılım alanı: {bank}\nAktarılan: {row.transfer_bytes} bayt"
                        + (
                            "\nMevcut imajın sürümü ve SHA-256 değeri eşleşti; tekrar gönderilmedi."
                            if reused
                            else ""
                        ),
                        finished=True,
                    )
                    db.commit()
                if plan.mode == "stage" or check_cancelled(id):
                    finish(id, "staged")
                    return
            load(id)
            set_phase(id, "rebooting")
            mutated = True
            await adapters.activate(cli, device, bank)
        set_phase(id, "verifying")
        version = await verify_running(id, device, secret, image, bank, recorder=recorder)
        finish(id, "succeeded", verified_version=version)
    except asyncio.CancelledError:
        with session_factory()() as db:
            row = db.get(m.FirmwareTarget, id)
            forced = bool(row.evidence.get("force_stop_requested"))
        unsafe = mutated or target_phase(id) in (
            "transferring",
            "image_verifying",
            "rebooting",
            "verifying",
            "reconcile",
        )
        finish(
            id,
            "attention" if unsafe else "cancelled" if forced else "failed",
            error_code="forced_stop" if forced else "interrupted",
        )
        raise
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, adapters.FirmwareError)
            else str(exc)
            if type(exc) is ValueError
            else type(exc).__name__
        )
        if code not in FAILURE_MESSAGES and code not in adapters.ERRORS:
            code = "network"
        # Never retain remote output, exception messages, temporary tokens or passwords.
        finish(id, "attention" if mutated or target_phase(id) == "reconcile" else "failed", error_code=code)
    finally:
        transfers.revoke(id)


FAILURE_MESSAGES = {
    "connection_changed": "Cihaz bağlantısı veya çalışan sürüm değişti; işlem durduruldu.",
    "actor_disabled": "Planı başlatan hesabın yönetici yetkisi artık geçerli değil.",
    "file_changed": "Firmware dosyasının bütünlüğü doğrulanamadı.",
    "image_family": "İmaj ailesi cihazın çalışan yazılım serisiyle eşleşmiyor.",
    "transfer_service": "Cihazın erişebileceği dosya sunucusu adresi yapılandırılmamış.",
    "not_staged": "İmaj ve konfigürasyon yedeği etkinleştirmeye hazır değil.",
    "version_mismatch": "Cihaz beklenen hedef sürümde çalışmıyor.",
    "reboot_timeout": "Yeniden başlatma sonrası hedef sürüm doğrulanamadı; müdahale gerekiyor.",
    "forced_stop": "Yönetici işlemi zorla durdurdu. Cihazda başlamış yazımın sonucu doğrulanmalı; otomatik tekrar yapılmadı.",
    "interrupted": "Firmware süreci kesildi. Yazma işlemi otomatik tekrarlanmadı.",
    "network": "SSH/dosya aktarımı tamamlanamadı. Erişim, host anahtarı ve yetkiyi kontrol edin.",
}


def target_phase(id):
    with session_factory()() as db:
        return db.get(m.FirmwareTarget, id).phase


def finish(id, status, *, error_code="", verified_version="", skipped=False):
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, id)
        if skipped:
            row.phase = "version_skipped"
            row.evidence = {**row.evidence, "skipped_current": True}
        if error_code:
            key = "verification_error" if row.phase == "reconcile" else "operation_error"
            row.evidence = {
                **row.evidence,
                key: {"code": error_code, "phase": row.phase, "at": now().isoformat()},
            }
            # The current result must describe this attempt. Earlier errors
            # remain in operation_error and the immutable command history,
            # including when a later read-only repair succeeded.
        row.status, row.error_code = status, error_code
        row.error = FAILURE_MESSAGES.get(error_code, adapters.ERRORS.get(error_code, ""))
        row.verified_version, row.finished_at = verified_version, now()
        history.add_event(
            db,
            row,
            kind="result",
            title="Cihaz zaten güncel; güncelleme atlandı"
            if skipped
            else history.RESULTS.get(status, status),
            status="failed"
            if error_code
            else "succeeded"
            if status in ("succeeded", "checked", "staged")
            else "info",
            response=row.error
            or (
                f"Çalışan sürüm: {verified_version}"
                + (
                    ". Hedefle aynı veya daha yeni; dosya aktarımı ve yeniden başlatma yapılmadı."
                    if skipped
                    else ""
                )
                if verified_version
                else history.RESULTS.get(status, status)
            ),
            finished=True,
        )
        if status in ("succeeded", "checked", "cancelled", "failed"):
            row.active_device = None
        if status == "succeeded":
            device = db.get(m.Device, row.device_id)
            device.software_version, device.last_seen_at = verified_version, now()
        db.commit()
    publish()


def settle(db, plan):
    rows = list(db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == plan.id)))
    if any(r.status == "running" for r in rows):
        return
    if plan.cancel_requested:
        plan.status, plan.finished_at = "cancelled", now()
        for row in rows:
            if row.status == "queued":
                if row.phase != "reconcile":
                    row.status, row.active_device = "cancelled", None
            elif row.status != "attention":
                row.active_device = None
    elif any(r.status in ("failed", "attention") for r in rows):
        plan.status = "paused"
    elif all(r.status in ("staged", "succeeded") for r in rows) and any(r.status == "staged" for r in rows):
        plan.status = "ready"
    elif all(r.status in ("succeeded", "checked") for r in rows):
        plan.status, plan.finished_at = "succeeded", now()


def claim():
    with session_factory()() as db:
        for row in db.scalars(
            select(m.FirmwareTarget)
            .where(
                m.FirmwareTarget.status == "running",
                m.FirmwareTarget.heartbeat_at < now() - timedelta(seconds=90),
            )
            .with_for_update(skip_locked=True)
        ):
            row.status = (
                "attention"
                if row.phase in ("transferring", "image_verifying", "rebooting", "verifying", "reconcile")
                else "failed"
            )
            row.error_code, row.error = "interrupted", FAILURE_MESSAGES["interrupted"]
            if row.status == "failed":
                row.active_device = None
        db.flush()
        for plan in db.scalars(
            select(m.FirmwarePlan)
            .where(
                or_(
                    m.FirmwarePlan.status.in_(("queued", "running")),
                    m.FirmwarePlan.id.in_(
                        select(m.FirmwareTarget.plan_id).where(
                            m.FirmwareTarget.status == "queued", m.FirmwareTarget.phase == "reconcile"
                        )
                    ),
                ),
                m.FirmwarePlan.available_at <= now(),
                m.FirmwarePlan.deleted_at.is_(None),
            )
            .order_by(m.FirmwarePlan.available_at, m.FirmwarePlan.id)
            .with_for_update(skip_locked=True)
            .limit(20)
        ):
            settle(db, plan)
            rows = list(
                db.scalars(
                    select(m.FirmwareTarget)
                    .where(m.FirmwareTarget.plan_id == plan.id)
                    .order_by(m.FirmwareTarget.stage, m.FirmwareTarget.id)
                )
            )
            reconcile = next((r for r in rows if r.status == "queued" and r.phase == "reconcile"), None)
            if plan.status == "paused" and not reconcile:
                continue
            if sum(r.status == "running" for r in rows) >= plan.concurrency:
                continue
            wanted = "staged" if plan.mode == "stage" else "checked" if plan.mode == "check" else "succeeded"
            pending = [r for r in rows if r.status != wanted and r.status != "succeeded"]
            if not pending:
                continue
            first_stage = min(r.stage for r in pending)
            row = reconcile or next(
                (r for r in pending if r.stage == first_stage and r.status == "queued"), None
            )
            if not row or (plan.cancel_requested and not reconcile):
                continue
            device = db.scalar(select(m.Device).where(m.Device.id == row.device_id).with_for_update())
            if db.scalar(
                select(m.Job.id)
                .where(m.Job.target_id == device.id, m.Job.status == "running")
                .with_for_update()
                .limit(1)
            ):
                continue
            if db.scalar(
                select(m.FirmwareTarget.id).where(
                    m.FirmwareTarget.active_device == device.id, m.FirmwareTarget.id != row.id
                )
            ):
                continue
            row.active_device, row.status, row.heartbeat_at = device.id, "running", now()
            if not reconcile:
                plan.status = "running"
            db.commit()
            publish()
            return row.id
        db.commit()
        return None


async def maintain_tasks(tasks):
    """One bounded worker pool; force cancellation belongs to the owning process."""
    for task in list(tasks):
        if task.done():
            if not task.cancelled() and task.exception():
                log.warning("firmware_task_failed error_class=%s", type(task.exception()).__name__)
            del tasks[task]
    forced = set()
    if tasks:
        with session_factory()() as db:
            for row, force in db.execute(
                select(m.FirmwareTarget, m.FirmwarePlan.force_stop_requested)
                .join(m.FirmwarePlan, m.FirmwarePlan.id == m.FirmwareTarget.plan_id)
                .where(m.FirmwareTarget.id.in_(tasks.values()))
            ):
                row.heartbeat_at = now()
                if force and row.evidence.get("force_stop_requested"):
                    forced.add(row.id)
            db.commit()
    cancelled = [task for task, id in tasks.items() if id in forced]
    for task in cancelled:
        task.cancel()
    if cancelled:
        await asyncio.gather(*cancelled, return_exceptions=True)
        for task in cancelled:
            del tasks[task]
    while len(tasks) < MAX_CONCURRENCY and not stop:
        id = claim()
        if not id:
            break
        tasks[asyncio.create_task(execute(id))] = id


async def loop():
    server = await transfers.start_ssh("0.0.0.0", settings().firmware_sftp_port)
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        transfers.TFTP, local_addr=("0.0.0.0", settings().firmware_tftp_port)
    )
    tasks = {}
    try:
        while not stop:
            try:
                try:
                    redis_client().set("netrix:firmware:heartbeat", now().isoformat(), ex=120)
                except Exception:
                    pass  # MariaDB remains the durable queue during Redis outages.
                await maintain_tasks(tasks)
            except Exception as exc:
                log.warning("firmware_cycle_failed error_class=%s", type(exc).__name__)
            await asyncio.sleep(1)
    finally:
        # A shutdown never blindly replays a flash/boot command on restart.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        transport.close()
        server.close()
        await server.wait_closed()


def request_stop(*args):
    global stop
    stop = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    asyncio.run(loop())
