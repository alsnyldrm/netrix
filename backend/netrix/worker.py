import argparse
import asyncio
import logging
import signal
import time
from datetime import timedelta

import asyncssh
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from . import models as m
from .alerting.engine import evaluate
from .configuration.failures import backup_failure
from .configuration.formatting import config_text
from .configuration.validation import BackupError, validate_cli_output
from .core import now, redis_client, session_factory
from .discovery.connection_tests import failure as connection_failure
from .discovery.connection_tests import probe as probe_connection
from .discovery.cx_mac import fetch_mac_vlans
from .discovery.identification import normalize, snmp_identity
from .discovery.interactive_tests import CAPACITY, POLL_SECONDS, interactive_condition
from .discovery.links import sync_links
from .discovery.neighbor_detail import AOS_SWITCH, enrich_neighbors
from .discovery.protocols import (
    NetworkError,
    SNMPCollector,
    fetch_config,
    fetch_identity,
    fetch_neighbor_detail,
)
from .discovery.targets import scope_targets
from .identity.security import decrypt, encrypt, secret_data
from .inventory.identity import apply_identity
from .ipam.connection_tests import KIND as INTEGRATION_TEST
from .ipam.connection_tests import execute as test_integration_connection
from .runtime_limits import device_slot, sql_point, sql_quick, sql_write
from .services import (
    CONNECTION_TESTS,
    IDENTITY_CONNECTION_FIELDS,
    SNMP_PROTOCOLS,
    authorized_device,
    backup_profile,
    connection_profile,
    get,
    in_scope,
    publish,
)

log = logging.getLogger("netrix.worker")
stop = False
BACKGROUND_CAPACITY = 4
PING_CAPACITY = 2
DISCOVERY_CAPACITY = 2
POINT_CAPACITY = 1
DISCOVERY_TARGETS = 16


class Cancelled(Exception):
    pass


class WorkerStopping(Exception):
    pass


def sync_interfaces(db, device, collected, job_id):
    interfaces = {
        row.name: row
        for row in db.scalars(
            select(m.Interface)
            .where(m.Interface.device_id == device.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    # ifIndex is an observation, never the durable identity of a port.
    for row in interfaces.values():
        row.if_index = None
    db.flush()
    names = set()
    for port in collected.get("interfaces", []):
        name = port["name"]
        if name in names:
            name = f"{name[:100]}#{port['if_index']}"
        names.add(name)
        row = interfaces.get(name)
        if not row:
            row = m.Interface(device_id=device.id, name=name)
            db.add(row)
        for key in ("if_index", "mac_address", "description", "speed_bps", "oper_status"):
            setattr(row, key, port.get(key))
        if row.oper_status == "up" and not row.auto_add_excluded and not row.is_deleted:
            row.is_managed = True
        db.flush()
    for row in interfaces.values():
        if row.name not in names:
            row.oper_status = "unknown"


def persist_collection(db, device, collected, job, protocol="snmpv3"):
    identity = normalize(collected.get("identity")) or snmp_identity(collected, {})
    apply_identity(db, device, identity, job.id, protocol)
    prior = db.scalar(
        select(m.Observation)
        .where(m.Observation.device_id == device.id, m.Observation.source.in_(SNMP_PROTOCOLS))
        .order_by(m.Observation.created_at.desc())
        .limit(1)
    )
    if prior and prior.evidence.get("hostname") != collected.get("hostname"):
        db.add(
            m.Event(
                device_id=device.id,
                kind="hostname_change",
                message=f"{device.name}: gözlemlenen hostname değişti",
                details={"fields": ["hostname"], "network_state_id": prior.network_state_id},
            )
        )
    evidence = dict(collected)
    evidence["identity"] = identity
    db.add(
        m.Observation(
            job_id=job.id,
            device_id=device.id,
            address=device.management_ip,
            source=protocol,
            evidence=evidence,
            confidence=1,
        )
    )
    sync_interfaces(db, device, collected, job.id)
    device.reachability, device.last_seen_at = "reachable", now()
    if job.kind != "discovery":
        sync_links(db, device, collected)


async def identify_device(job_id, collector):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        device = get(db, m.Device, job.target_id)
        version_only = bool(job.result.get("version_only"))
        required_fields = {"software_version"} if version_only else {"vendor", "model", "kind"}
        authorized_device(db, device)
        if job.cancel_requested:
            raise Cancelled()
        existing = db.scalar(select(m.Observation).where(m.Observation.job_id == job_id))
        if existing:
            return {
                "fields": sorted(existing.evidence.get("identity", {})),
                "source_read_id": existing.id,
                "recovered": True,
            }
        connection = tuple(getattr(device, key) for key in IDENTITY_CONNECTION_FIELDS)
        credentials = []
        for profile in (device.snmp_credential_id, device.config_credential_id):
            if profile:
                credential = get(db, m.Credential, profile)
                credentials.append(
                    (credential.protocol, secret_data(credential), credential.id, credential.updated_at)
                )
    fields, sources, attempts = {}, {}, []
    for protocol, secret, _, _ in credentials:
        if (required_fields | {"software_version"}) <= fields.keys():
            break
        try:
            if protocol in SNMP_PROTOCOLS:
                collect = getattr(collector, "software" if version_only else "identify", collector.collect)
                response = await collect(device.management_ip, device.snmp_port, secret)
                values = normalize(response.get("identity")) or snmp_identity(response, {})
            else:
                values = normalize(await fetch_identity(device, secret))
            if version_only:
                values = {k: v for k, v in values.items() if k == "software_version"}
            attempts.append({"protocol": protocol, "status": "read", "fields": sorted(values)})
            for key, value in values.items():
                if key not in fields:
                    fields[key], sources[key] = value, protocol
        except Exception as exc:
            # Keep failures useful without retaining device output, credentials or exception text.
            attempts.append({"protocol": protocol, "status": "failed", "error_class": type(exc).__name__})
    if attempts and all(attempt["status"] == "failed" for attempt in attempts):
        raise NetworkError("Cihaz kimlik bilgileri okunamadı")
    neighbor_data = None
    if device.adapter in AOS_SWITCH and not version_only:
        ssh_secret = next((s for p, s, _, _ in credentials if p == "ssh"), None)
        if ssh_secret:
            try:
                neighbor_data = enrich_neighbors({}, await fetch_neighbor_detail(device, ssh_secret))
            except Exception as exc:
                attempts.append(
                    {"protocol": "ssh_detail", "status": "failed", "error_class": type(exc).__name__}
                )
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        current = db.scalar(select(m.Device).where(m.Device.id == device.id).with_for_update())
        authorized_device(db, current)
        if job.cancel_requested:
            raise Cancelled()
        if connection != tuple(getattr(current, key) for key in IDENTITY_CONNECTION_FIELDS) or any(
            get(db, m.Credential, profile_id).updated_at != updated
            for _, _, profile_id, updated in credentials
        ):
            raise NetworkError("Bağlantı bilgileri değişti; kimlik sorgusu yeniden denenmeli")
        apply_identity(db, current, fields, job.id, sources)
        if neighbor_data is not None:
            sync_links(db, current, neighbor_data)
        db.add(
            m.Observation(
                device_id=current.id,
                job_id=job.id,
                address=current.management_ip,
                source="identity",
                evidence={
                    "identity": fields,
                    "field_sources": sources,
                    "attempts": attempts,
                    **({"neighbor_detail": neighbor_data} if neighbor_data is not None else {}),
                },
                confidence=0.9,
            )
        )
        if fields:
            current.last_seen_at, current.reachability = now(), "reachable"
        job.progress, job.total = 1, 1
        db.commit()
        publish()
    return {
        "fields": sorted(fields),
        "missing_fields": sorted(required_fields - fields.keys()),
        "field_sources": sources,
        "attempts": attempts,
    }


async def test_device_connection(job_id, collector):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        device = get(db, m.Device, job.target_id)
        authorized_device(db, device)
        if job.cancel_requested:
            raise Cancelled()
        protocol = CONNECTION_TESTS[job.kind]
        profile = connection_profile(db, device, protocol)
        if not profile:
            raise ValueError("Seçilen protokol için erişim profili yok")
        if job.result.get("protocol") == protocol:
            return job.result
        secret = secret_data(profile)

        def signature(target, credential):
            return (
                target.management_ip,
                target.vrf_id,
                credential.id,
                credential.updated_at,
                target.snmp_port if protocol in SNMP_PROTOCOLS else target.config_port,
                target.identity_path if protocol == "rest" else "",
                target.ssh_trust_host_key if protocol == "ssh" else False,
            )

        connection = signature(device, profile)
    started = time.monotonic()
    result = {
        "protocol": protocol,
        "target": device.management_ip,
        "port": device.snmp_port if protocol in SNMP_PROTOCOLS else device.config_port,
    }
    try:
        result.update(success=True, message=await probe_connection(device, protocol, secret, collector))
    except Exception as exc:
        code, message = connection_failure(exc, protocol)
        result.update(success=False, error_code=code, message=message)
    result.update(duration_ms=round((time.monotonic() - started) * 1000), checked_at=now().isoformat())
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        current = get(db, m.Device, device.id)
        authorized_device(db, current)
        if job.cancel_requested:
            raise Cancelled()
        profile = connection_profile(db, current, protocol)
        if not profile or signature(current, profile) != connection:
            result.update(
                success=False,
                error_code="connection_changed",
                message="Test sırasında cihazın bağlantı bilgileri değişti. Güncel bilgilerle yeniden test edin.",
            )
        job.progress, job.total = 1, 1
        db.commit()
    return result


async def discover(job_id, collector):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        scope = get(db, m.Scope, job.target_id)
        if not scope.enabled:
            raise Cancelled()
        profile_ids = scope.credential_ids
        targets = scope_targets(scope)
        job.total = len(targets)
        job.progress = db.scalar(
            select(func.count()).select_from(m.Observation).where(m.Observation.job_id == job_id)
        )
        scope.last_run_at = now()
        db.commit()
    semaphore = asyncio.Semaphore(DISCOVERY_TARGETS)

    def advance():
        # A separate statement: this row changes every second under the heartbeat.
        with session_factory()() as db:
            db.execute(update(m.Job).where(m.Job.id == job_id).values(progress=m.Job.progress + 1))
            db.commit()

    async def target(address):
        async with semaphore:
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                current_scope = get(db, m.Scope, job.target_id)
                if job.cancel_requested or not in_scope(address, current_scope):
                    raise Cancelled()
                prior = db.scalar(
                    select(m.Observation.id).where(
                        m.Observation.job_id == job_id, m.Observation.address == address
                    )
                )
                if prior:
                    return True
                existing_device = db.scalar(
                    select(m.Device).where(
                        m.Device.vrf_id == current_scope.vrf_id, m.Device.management_ip == address
                    )
                )
                port = existing_device.snmp_port if existing_device else 161
            for profile_id in profile_ids:
                with session_factory()() as db:
                    job = get(db, m.Job, job_id)
                    current_scope = get(db, m.Scope, job.target_id)
                    if job.cancel_requested or not in_scope(address, current_scope):
                        raise Cancelled()
                    if profile_id not in current_scope.credential_ids:
                        continue
                    profile = get(db, m.Credential, profile_id)
                    profile_version = profile.updated_at
                    secret = secret_data(profile)
                try:
                    # Reject silent/wrong profiles with a bounded system-OID read.
                    # Keep the configured profile order, and cap expensive table walks.
                    if probe := getattr(collector, "discovery_probe", getattr(collector, "probe", None)):
                        async with asyncio.timeout(3):
                            await probe(address, port, secret)
                    async with device_slot():
                        async with asyncio.timeout(180):
                            collected = await collector.collect(address, port, secret)
                    break
                except (NetworkError, TimeoutError, OSError):
                    continue
            else:
                await sql_quick(advance)
                return False

            from .ipam.network import inventory_mac_profile, read_context

            cx_context = None
            tables = collected.get("tables") or {}
            if tables.get("vlan_fdb_port") and not tables.get("vlan_fdb_id"):
                with session_factory()() as db:
                    current_scope = get(db, m.Scope, scope.id)
                    job = get(db, m.Job, job_id)
                    if job.cancel_requested or not in_scope(address, current_scope):
                        raise Cancelled()
                    current = db.get(m.Device, existing_device.id) if existing_device else None
                    ssh = inventory_mac_profile(db, current) if current else None
                    if (
                        ssh
                        and not current.archived
                        and current.lifecycle_status == "active"
                        and current.management_ip == address
                        and current.vrf_id == current_scope.vrf_id
                        and current.snmp_port == port
                        and current.snmp_credential_id == profile_id
                    ):
                        cx_context = read_context(current, profile, ssh)
                        ssh_secret = secret_data(ssh)
                if cx_context:
                    try:
                        async with device_slot():
                            collected["cx_mac_vlans"] = await fetch_mac_vlans(current, ssh_secret)
                    except (TimeoutError, OSError, BackupError, NetworkError, asyncssh.Error) as exc:
                        collected["cx_mac_vlan_error"] = type(exc).__name__

            def persist():
                with session_factory()() as db:
                    job = get(db, m.Job, job_id)
                    current_scope = get(db, m.Scope, job.target_id)
                    profile = db.get(m.Credential, profile_id)
                    if (
                        job.cancel_requested
                        or not in_scope(address, current_scope)
                        or profile_id not in current_scope.credential_ids
                        or not profile
                        or profile.updated_at != profile_version
                    ):
                        raise Cancelled()
                    device = db.scalar(
                        select(m.Device)
                        .where(m.Device.vrf_id == current_scope.vrf_id, m.Device.management_ip == address)
                        .with_for_update()
                    )
                    if not device:
                        device = m.Device(
                            name=(collected.get("hostname") or address)[:120],
                            management_ip=address,
                            vrf_id=current_scope.vrf_id,
                            site_id=current_scope.site_id,
                            snmp_credential_id=profile_id,
                            kind="other",
                        )
                        db.add(device)
                        db.flush()
                        db.add(
                            m.Event(
                                device_id=device.id,
                                kind="device_discovered",
                                message=f"{device.name}: yeni cihaz keşfedildi",
                                details={"address": address},
                            )
                        )
                    device.discovery_scope_id = current_scope.id
                    # Keep a separately managed profile outside this scope intact.
                    if (
                        not device.snmp_credential_id
                        or device.snmp_credential_id in current_scope.credential_ids
                    ):
                        device.snmp_credential_id = profile_id
                    if cx_context:
                        current_ssh = inventory_mac_profile(db, device)
                        if cx_context == read_context(device, profile, current_ssh):
                            if "cx_mac_vlans" in collected:
                                collected["read_context"] = cx_context
                        else:
                            collected.pop("cx_mac_vlans", None)
                            collected.pop("cx_mac_vlan_error", None)
                    persist_collection(db, device, collected, job, secret["protocol"])
                    db.commit()
                    publish()

            await sql_write(persist)
            await sql_quick(advance)
            return True

    pending = iter(targets)

    async def consume():
        succeeded = completed = 0
        for address in pending:
            succeeded += bool(await target(address))
            completed += 1
            # Yield even when an already completed observation skips network I/O.
            await asyncio.sleep(0)
        return succeeded, completed

    tasks = [asyncio.create_task(consume()) for _ in range(DISCOVERY_TARGETS)]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    succeeded = sum(result[0] for result in results)
    completed = sum(result[1] for result in results)
    return {"reachable": succeeded, "unresponsive": completed - succeeded, "total": completed}


async def collect_backup(job_id):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        device = get(db, m.Device, job.target_id)
        authorized_device(db, device)
        credential = backup_profile(db, device)
        signature = tuple(getattr(device, key) for key in IDENTITY_CONNECTION_FIELDS) + (
            credential.updated_at,
        )
        secret = secret_data(credential)
        existing = db.scalar(select(m.Snapshot.id).where(m.Snapshot.job_id == job_id))
        if existing:
            return {"recovered": True}
    data = await fetch_config(device, secret)
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        current = db.scalar(select(m.Device).where(m.Device.id == device.id).with_for_update())
        authorized_device(db, current)
        if job.cancel_requested:
            raise Cancelled()
        current_profile = backup_profile(db, current)
        if signature != tuple(getattr(current, key) for key in IDENTITY_CONNECTION_FIELDS) + (
            current_profile.updated_at,
        ):
            raise BackupError("connection_changed")
        validate_cli_output(data)
        data = config_text(data)
        from .configuration import baselines

        previous = baselines.base(db, current)
        fingerprint = baselines.fingerprint(data)
        changed = (
            previous is not None and baselines.fingerprint(decrypt(previous.encrypted_content)) != fingerprint
        )
        db.add(
            m.Snapshot(
                device_id=current.id,
                job_id=job.id,
                fingerprint=fingerprint,
                encrypted_content=encrypt(data),
                size_bytes=len(data.encode()),
                changed=changed,
            )
        )
        current.last_backup_at = now()
        db.flush()
        from .configuration.management import prune

        baselines.base(db, current)
        prune(db, current)
        if changed:
            db.add(
                m.Event(
                    device_id=current.id,
                    kind="config_change",
                    message=f"{current.name}: konfigürasyon değişikliği tespit edildi",
                )
            )
        evaluate(db, current, "config_change", int(changed))
        job.progress, job.total = 1, 1
        db.commit()
        publish()
    return {"saved": True}


def claim(interactive=None, *, exclude_kinds=(), exclude_targets=(), include_kinds=()):
    lane = (
        [] if interactive is None else [interactive_condition() if interactive else ~interactive_condition()]
    )
    with session_factory()() as db:
        stale = list(
            db.scalars(
                select(m.Job)
                .where(m.Job.status == "running", m.Job.heartbeat_at < now() - timedelta(seconds=90), *lane)
                .with_for_update(skip_locked=True)
            )
        )
        for job in stale:
            job.status = (
                "cancelled"
                if job.cancel_requested
                else "failed"
                if job.attempts >= 3 or job.result.get("interactive")
                else "queued"
            )
            job.error = (
                "Etkileşimli işlem kesildi. Yeniden deneyin."
                if job.result.get("interactive")
                else "Worker bağlantısı kesildi; görev yeniden ele alındı"
            )
            if job.status in ("failed", "cancelled"):
                job.active_key, job.finished_at = None, now()
        db.flush()
        eligible = [
            m.Job.status == "queued",
            m.Job.available_at <= now(),
            *lane,
            m.Job.target_id.not_in(
                select(m.FirmwareTarget.active_device).where(
                    m.FirmwareTarget.status == "running", m.FirmwareTarget.active_device.is_not(None)
                )
            ),
        ]
        if include_kinds:
            eligible.append(m.Job.kind.in_(include_kinds))
        if exclude_kinds:
            eligible.append(m.Job.kind.not_in(exclude_kinds))
        if exclude_targets:
            eligible.append(m.Job.target_id.not_in(exclude_targets))
        job = db.scalar(
            select(m.Job)
            .where(*eligible)
            .order_by(m.Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job:
            # Both workers serialize on the same device before claiming work.
            db.scalar(select(m.Device).where(m.Device.id == job.target_id).with_for_update())
            # Current read closes the race with the dedicated firmware claimant.
            if db.scalar(
                select(m.FirmwareTarget.id)
                .where(
                    m.FirmwareTarget.active_device == job.target_id,
                    m.FirmwareTarget.status == "running",
                )
                .with_for_update()
            ):
                db.commit()
                return None
            job.status, job.heartbeat_at = "running", now()
            job.attempts += 1
            job.error = ""
            job.result = {**job.result, "started_at": job.result.get("started_at") or now().isoformat()}
            db.commit()
            publish(ping_vlan=job.target_id) if job.kind == "ipam_ping" else publish()
            return job.id
        db.commit()
        return None


async def execute(job_id, collector=None, *, heartbeat_role="worker"):
    collector = collector or SNMPCollector()
    with session_factory()() as db:
        initial = get(db, m.Job, job_id)
        kind, interactive = initial.kind, initial.result.get("interactive", False)
        from .ipam.triggers import SCHEDULED_ORIGINS, allowed_origin

        if kind in SCHEDULED_ORIGINS and not allowed_origin(
            kind, initial.result.get("ipam_origin"), initial.requested_by
        ):
            initial.status, initial.active_key, initial.finished_at = "cancelled", None, now()
            initial.error = "Geçerli tetikleyicisi olmayan IPAM işi iptal edildi"
            db.commit()
            return
    from .configuration.management import compare_live
    from .ipam.jobs import KINDS
    from .ipam.jobs import execute as execute_ipam

    if kind not in (
        *KINDS,
        INTEGRATION_TEST,
        "compare",
        "discovery",
        "identify",
        "backup",
        *CONNECTION_TESTS,
    ):
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            job.status, job.active_key, job.finished_at = "cancelled", None, now()
            job.error = "Desteklenmeyen görev türü"
            db.commit()
        return

    task = asyncio.create_task(
        test_integration_connection(job_id)
        if kind == INTEGRATION_TEST
        else execute_ipam(job_id, kind, collector)
        if kind in KINDS
        else compare_live(job_id)
        if kind == "compare"
        else discover(job_id, collector)
        if kind == "discovery"
        else (
            test_device_connection(job_id, collector)
            if kind in CONNECTION_TESTS
            else (identify_device(job_id, collector) if kind == "identify" else collect_backup(job_id))
        )
    )
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.25 if interactive else 1)

            def beat():
                # Write before reading: no snapshot is open for MariaDB to reject (1020).
                with session_factory()() as db:
                    db.execute(update(m.Job).where(m.Job.id == job_id).values(heartbeat_at=now()))
                    db.commit()
                    return get(db, m.Job, job_id).cancel_requested

            cancelled = await (sql_point(beat) if kind == "ipam_address_scan" else sql_quick(beat))
            heartbeat(heartbeat_role)
            if cancelled or (stop and not task.done()):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Cancelled):
                    pass
                if stop and not cancelled and not interactive:
                    raise WorkerStopping()
                raise Cancelled()
        result = task.result()
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                job.status = "cancelled"
            elif kind in (*CONNECTION_TESTS, INTEGRATION_TEST):
                job.status = "succeeded" if result.get("success") is True else "failed"
                job.error = (
                    ""
                    if result.get("success") is True
                    else result.get("message", "Bağlantı testi başarısız.")
                )
            elif kind == "identify":
                fields = result.get("fields", {})
                expected = (
                    {"software_version"} if job.result.get("version_only") else {"vendor", "model", "kind"}
                )
                complete = expected <= set(fields)
                job.status = "succeeded" if complete else "partial" if fields else "failed"
                job.error = "" if complete else "Okunamayan alanlarda mevcut bilgiler korundu."
            elif kind == "discovery" and result.get("unresponsive"):
                job.status = "partial" if result["reachable"] else "failed"
            elif kind == "ipam_ping" and result.get("ping_failed"):
                job.status = "partial"
                job.error = f"{result['ping_failed']} IP için ping işlemi çalıştırılamadı; önceki ping durumları korundu."
            elif kind in ("ipam_discover", "ipam_address_scan") and (
                (result.get("network") or {}).get("failed") or result.get("source_failed")
            ):
                job.status = "partial"
                job.error = (
                    "Tarama tamamlandı; IP sonuçlarında sorun var. IP ayrıntısındaki Sonuç alanını inceleyin."
                    if result.get("problems") or result.get("resolution_status") == "problem"
                    else "Tarama ve eşleştirme tamamlandı; bazı gateway/switch veya entegrasyon kaynakları okunamadı. Eksik kaynakları görev ayrıntısından kontrol edin."
                )
            else:
                job.status = "succeeded"
            job.result, job.finished_at, job.active_key = {**job.result, **result}, now(), None
            db.commit()
    except WorkerStopping:
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                job.status, job.finished_at, job.active_key = "cancelled", now(), None
            else:
                job.status, job.available_at = "queued", now()
                job.attempts = max(0, job.attempts - 1)
                job.error = "Hizmet yeniden başlatılıyor; görev otomatik devam edecek."
            db.commit()
    except Exception as exc:
        db_code = None
        if isinstance(exc, OperationalError):
            args = getattr(getattr(exc, "orig", None), "args", ())
            db_code = args[0] if args and isinstance(args[0], int) else None
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if db_code is not None:
                job.result = {**job.result, "database_error_code": db_code}
            cancelled = job.cancel_requested or isinstance(exc, Cancelled)
            if cancelled:
                job.status = "cancelled"
            elif (
                not interactive
                and job.attempts < 3
                and isinstance(exc, (NetworkError, OSError, TimeoutError, OperationalError))
            ):
                job.status = "queued"
                job.available_at = now() + timedelta(seconds=15 * 2 ** (job.attempts - 1))
            else:
                job.status = "failed"
            job.error = (
                "Görev iptal edildi"
                if cancelled
                else str(exc)
                if isinstance(exc, BackupError)
                else "Cihaz işlemi başarısız. Kapsam, erişim profili, protokol ve host anahtarını kontrol edin."
            )
            if kind in KINDS and not cancelled:
                job.error = (
                    "Entegrasyon okunamadı. Sunucu, TLS güveni, kullanıcı/parola ve salt okunur API/WinRM yetkilerini kontrol edin."
                    if kind == "integration"
                    else "IPAM işlemi başarısız. Yetkili kapsamı, güncel port eşleşmesini ve DNS/SNMP/ICMP erişimini kontrol edin."
                )
            if kind in ("backup", "compare") and not cancelled:
                code, job.error = backup_failure(exc)
                job.result = {**job.result, "error_code": code}
            if job.status != "queued":
                job.active_key, job.finished_at = None, now()
            db.commit()
            log.warning("job_failed job_id=%s error_class=%s db_code=%s", job_id, type(exc).__name__, db_code)
    finally:
        if not task.done():
            task.cancel()
        publish(ping_vlan=initial.target_id) if kind == "ipam_ping" else publish()


def heartbeat(role):
    try:
        redis_client().set(f"netrix:{role}:heartbeat", now().isoformat(), ex=90)
    except Exception:
        pass


async def worker_loop():
    # One process with bounded async slots: long scans cannot occupy every slot.
    # Different operations for the same target stay sequential.
    tasks = {}
    last_heartbeat = 0.0
    try:
        while not stop:
            try:
                if time.monotonic() - last_heartbeat >= 2:
                    heartbeat("worker")
                    last_heartbeat = time.monotonic()
                for task in list(tasks):
                    if task.done():
                        if not task.cancelled() and task.exception():
                            log.warning(
                                "background_task_failed error_class=%s", type(task.exception()).__name__
                            )
                        del tasks[task]
                while not stop and sum(kind == "ipam_ping" for kind, _ in tasks.values()) < PING_CAPACITY:
                    ping_id = claim(
                        interactive=False,
                        include_kinds=("ipam_ping",),
                        exclude_targets=tuple(
                            target for kind, target in tasks.values() if kind == "ipam_ping"
                        ),
                    )
                    if not ping_id:
                        break
                    with session_factory()() as db:
                        ping_target = get(db, m.Job, ping_id).target_id
                    tasks[asyncio.create_task(execute(ping_id))] = ("ipam_ping", ping_target)
                while (
                    not stop
                    and sum(kind == "ipam_address_scan" for kind, _ in tasks.values()) < POINT_CAPACITY
                ):
                    point_id = claim(
                        interactive=False,
                        include_kinds=("ipam_address_scan",),
                        exclude_targets=tuple(
                            target for kind, target in tasks.values() if kind == "ipam_address_scan"
                        ),
                    )
                    if not point_id:
                        break
                    with session_factory()() as db:
                        point_target = get(db, m.Job, point_id).target_id
                    tasks[asyncio.create_task(execute(point_id))] = ("ipam_address_scan", point_target)
                while (
                    not stop
                    and sum(kind not in ("ipam_ping", "ipam_address_scan") for kind, _ in tasks.values())
                    < BACKGROUND_CAPACITY
                ):
                    scans = sum(kind in ("discovery", "ipam_discover") for kind, _ in tasks.values())
                    job_id = claim(
                        interactive=False,
                        exclude_kinds=("ipam_ping", "discovery", "ipam_discover", "ipam_address_scan")
                        if scans >= DISCOVERY_CAPACITY
                        else ("ipam_ping", "ipam_address_scan"),
                        exclude_targets=tuple(
                            target for kind, target in tasks.values() if target and kind != "ipam_ping"
                        ),
                    )
                    if not job_id:
                        break
                    with session_factory()() as db:
                        job = get(db, m.Job, job_id)
                        metadata = job.kind, job.target_id
                    tasks[asyncio.create_task(execute(job_id))] = metadata
                await asyncio.sleep(0.25)
            except Exception as exc:
                log.warning("worker_cycle_failed error_class=%s", type(exc).__name__)
                await asyncio.sleep(1)
    finally:
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def interactive_test_loop():
    tasks = set()
    last_heartbeat = 0.0
    try:
        while not stop:
            try:
                if time.monotonic() - last_heartbeat >= 2:
                    heartbeat("tests")
                    last_heartbeat = time.monotonic()
                done = {task for task in tasks if task.done()}
                for task in done:
                    # Surface failures without logging connection data.
                    if not task.cancelled() and task.exception():
                        log.warning("interactive_test_failed error_class=%s", type(task.exception()).__name__)
                tasks -= done
                while len(tasks) < CAPACITY:
                    job_id = claim(interactive=True)
                    if not job_id:
                        break
                    tasks.add(asyncio.create_task(execute(job_id, heartbeat_role="tests")))
                await asyncio.sleep(POLL_SECONDS)
            except Exception as exc:
                log.warning("interactive_test_cycle_failed error_class=%s", type(exc).__name__)
                await asyncio.sleep(1)
    finally:
        # execute() observes stop and records cancellation; do not abandon probes.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def request_stop(*args):
    global stop
    stop = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive-tests", action="store_true")
    args = parser.parse_args()
    asyncio.run(interactive_test_loop() if args.interactive_tests else worker_loop())
