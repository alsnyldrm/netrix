import argparse
import asyncio
import hashlib
import ipaddress
import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from . import models as m
from .alerting.engine import evaluate
from .configuration.failures import backup_failure
from .configuration.history import previous_valid_snapshot
from .configuration.validation import BackupError, validate_cli_output
from .core import now, redis_client, session_factory
from .discovery.connection_tests import failure as connection_failure
from .discovery.connection_tests import probe as probe_connection
from .discovery.correlation import correlate
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
from .identity.security import encrypt, secret_data
from .inventory.identity import apply_identity
from .monitoring.rates import calculate_rate
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


class Cancelled(Exception):
    pass


def scope_targets(scope):
    network = ipaddress.ip_network(scope.cidr)
    if (network.version == 6 or network.num_addresses > 1024) and not scope.seeds:
        raise NetworkError("Geniş ağ ve IPv6 açık hedef listesi gerektirir")
    candidates = scope.seeds or [str(ip) for ip in network.hosts()]
    return [
        ip
        for ip in candidates
        if in_scope(ip, scope)
        and not any(
            (
                ipaddress.ip_address(ip).is_multicast,
                ipaddress.ip_address(ip).is_loopback,
                ipaddress.ip_address(ip).is_link_local,
                ipaddress.ip_address(ip).is_unspecified,
            )
        )
    ][:1024]


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
    utilizations = []
    for port in collected.get("interfaces", []):
        name = port["name"]
        if name in names:
            name = f"{name[:100]}#{port['if_index']}"
        names.add(name)
        row = interfaces.get(name)
        if not row:
            row = m.Interface(device_id=device.id, name=name)
            db.add(row)
        elif row.oper_status != port["oper_status"]:
            db.add(
                m.Event(
                    device_id=device.id,
                    kind="port_change",
                    message=f"{device.name} / {name}: {port['oper_status']}",
                    details={"previous": row.oper_status, "current": port["oper_status"]},
                )
            )
        for key in ("if_index", "mac_address", "description", "speed_bps", "oper_status"):
            setattr(row, key, port.get(key))
        if row.oper_status == "up" and not row.auto_add_excluded and not row.is_deleted:
            row.is_managed = True
        db.flush()
        counters = port.get("counters")
        if counters and row.is_managed and row.monitoring_enabled and not row.is_deleted:
            existing = db.scalar(
                select(m.Sample.id).where(m.Sample.interface_id == row.id, m.Sample.job_id == job_id)
            )
            if existing:
                continue
            previous = db.scalar(
                select(m.Sample)
                .where(m.Sample.interface_id == row.id)
                .order_by(m.Sample.created_at.desc())
                .limit(1)
            )
            old = {key: int(getattr(previous, key)) for key in counters} if previous else None
            elapsed = (now() - previous.created_at).total_seconds() if previous else 0
            incoming, outgoing, quality = calculate_rate(old, counters, elapsed, row.speed_bps)
            db.add(
                m.Sample(
                    interface_id=row.id,
                    job_id=job_id,
                    **counters,
                    speed_bps=row.speed_bps,
                    in_bps=incoming,
                    out_bps=outgoing,
                    quality=quality,
                )
            )
            if incoming is not None and row.speed_bps:
                utilizations.append(max(incoming, outgoing) * 100 / int(row.speed_bps))

    for row in interfaces.values():
        if row.name not in names:
            row.oper_status = "unknown"
    if utilizations:
        evaluate(db, device, "utilization", max(utilizations))


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
                details={"previous": prior.evidence.get("hostname"), "current": collected.get("hostname")},
            )
        )
    evidence = {key: value for key, value in collected.items() if key != "interfaces"}
    evidence["identity"] = identity
    evidence["port_candidates"] = correlate(collected.get("tables", {}), collected.get("neighbors", []))
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
    sync_links(db, device, collected)
    from .ipam.service import inventory_observations

    inventory_observations(db, device, collected)
    evaluate(db, device, "availability", 1)
    evaluate(db, device, "no_data", 0)


async def identify_device(job_id, collector):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        device = get(db, m.Device, job.target_id)
        authorized_device(db, device)
        if job.cancel_requested:
            raise Cancelled()
        existing = db.scalar(select(m.Observation).where(m.Observation.job_id == job_id))
        if existing:
            return {"fields": existing.evidence.get("identity", {}), "recovered": True}
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
        if len(fields) == 3:
            break
        try:
            if protocol in SNMP_PROTOCOLS:
                collect = getattr(collector, "identify", collector.collect)
                response = await collect(device.management_ip, device.snmp_port, secret)
                values = normalize(response.get("identity")) or snmp_identity(response, {})
            else:
                values = normalize(await fetch_identity(device, secret))
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
    if device.adapter in AOS_SWITCH:
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
        "fields": fields,
        "missing_fields": sorted({"vendor", "model", "kind"} - fields.keys()),
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
        secret = secret_data(get(db, m.Credential, scope.credential_id))
        targets = scope_targets(scope)
        job.total = len(targets)
        job.progress = db.scalar(
            select(func.count()).select_from(m.Observation).where(m.Observation.job_id == job_id)
        )
        scope.last_run_at = now()
        db.commit()
    semaphore = asyncio.Semaphore(4)

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
            try:
                collected = await collector.collect(address, port, secret)
            except (NetworkError, TimeoutError, OSError):
                with session_factory()() as db:
                    job = get(db, m.Job, job_id)
                    job.progress += 1
                    db.commit()
                return False
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                current_scope = get(db, m.Scope, job.target_id)
                if job.cancel_requested or not in_scope(address, current_scope):
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
                        snmp_credential_id=current_scope.credential_id,
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
                persist_collection(db, device, collected, job, secret["protocol"])
                job.progress += 1
                db.commit()
                publish()
            return True

    tasks = [asyncio.create_task(target(address)) for address in targets]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    succeeded = sum(results)
    return {"reachable": succeeded, "unresponsive": len(results) - succeeded, "total": len(results)}


async def collect_device(job_id, collector):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        device = get(db, m.Device, job.target_id)
        authorized_device(db, device)
        credential = (
            backup_profile(db, device)
            if job.kind == "backup"
            else get(db, m.Credential, device.snmp_credential_id)
        )
        signature = tuple(getattr(device, key) for key in IDENTITY_CONNECTION_FIELDS) + (
            credential.updated_at,
        )
        secret = secret_data(credential)
        detail_profile = (
            db.get(m.Credential, device.config_credential_id)
            if job.kind != "backup" and device.adapter in AOS_SWITCH and device.config_credential_id
            else None
        )
        detail_secret = (
            secret_data(detail_profile) if detail_profile and detail_profile.protocol == "ssh" else None
        )
        detail_version = detail_profile.updated_at if detail_secret else None
        existing = (
            db.scalar(select(m.Snapshot.id).where(m.Snapshot.job_id == job_id))
            if job.kind == "backup"
            else db.scalar(select(m.Observation.id).where(m.Observation.job_id == job_id))
        )
        if existing:
            return {"recovered": True}
    try:
        data = (
            await fetch_config(device, secret)
            if job.kind == "backup"
            else await collector.collect(device.management_ip, device.snmp_port, secret)
        )
        if job.kind != "backup" and detail_secret:
            try:
                detail = await fetch_neighbor_detail(
                    device, detail_secret, [n["interface_name"] for n in data.get("neighbors", [])]
                )
                enrich_neighbors(data, detail)
            except Exception as exc:
                data["neighbor_detail"] = {"status": "failed", "error_class": type(exc).__name__}
    except Exception:
        if job.kind == "monitor":
            with session_factory()() as db:
                current = get(db, m.Device, device.id)
                current.reachability, current.last_monitor_at = "unreachable", now()
                evaluate(db, current, "availability", 0)
                db.commit()
                publish()
        raise
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        current = db.scalar(select(m.Device).where(m.Device.id == device.id).with_for_update())
        authorized_device(db, current)
        if job.cancel_requested:
            raise Cancelled()
        if job.kind == "backup":
            current_profile = backup_profile(db, current)
            if signature != tuple(getattr(current, key) for key in IDENTITY_CONNECTION_FIELDS) + (
                current_profile.updated_at,
            ):
                raise BackupError("connection_changed")
            validate_cli_output(data)
            previous, previous_content = previous_valid_snapshot(db, current.id)
            fingerprint = hashlib.sha256(data.encode()).hexdigest()
            changed = previous is not None and previous_content != data
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
        else:
            if signature != tuple(getattr(current, key) for key in IDENTITY_CONNECTION_FIELDS) + (
                get(db, m.Credential, current.snmp_credential_id).updated_at,
            ) or (
                detail_version
                and get(db, m.Credential, current.config_credential_id).updated_at != detail_version
            ):
                raise NetworkError("Bağlantı bilgileri değişti; gözlem yeniden alınmalı")
            persist_collection(db, current, data, job, secret["protocol"])
            current.last_monitor_at = now()
        job.progress, job.total = 1, 1
        db.commit()
        publish()
    return {"saved": True}


def claim(interactive=None):
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
                "Test çalıştırıcısı kesildi. Yeniden test edin."
                if job.result.get("interactive")
                else "Worker bağlantısı kesildi; görev yeniden ele alındı"
            )
            if job.status in ("failed", "cancelled"):
                job.active_key, job.finished_at = None, now()
        db.flush()
        job = db.scalar(
            select(m.Job)
            .where(m.Job.status == "queued", m.Job.available_at <= now(), *lane)
            .order_by(m.Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job:
            job.status, job.heartbeat_at = "running", now()
            job.attempts += 1
            job.error = ""
            db.commit()
            return job.id
        db.commit()
        return None


async def execute(job_id, collector=None, *, heartbeat_role="worker"):
    collector = collector or SNMPCollector()
    with session_factory()() as db:
        initial = get(db, m.Job, job_id)
        kind, interactive = initial.kind, initial.result.get("interactive", False)
    from .configuration.management import compare_live
    from .ipam.jobs import KINDS
    from .ipam.jobs import execute as execute_ipam

    task = asyncio.create_task(
        execute_ipam(job_id, kind, collector)
        if kind in KINDS
        else compare_live(job_id)
        if kind == "compare"
        else discover(job_id, collector)
        if kind == "discovery"
        else (
            test_device_connection(job_id, collector)
            if kind in CONNECTION_TESTS
            else (
                identify_device(job_id, collector)
                if kind == "identify"
                else collect_device(job_id, collector)
            )
        )
    )
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.25 if interactive else 5)
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                job.heartbeat_at = now()
                cancelled = job.cancel_requested
                db.commit()
            heartbeat(heartbeat_role)
            if cancelled or stop:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Cancelled):
                    pass
                raise Cancelled()
        result = task.result()
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                job.status = "cancelled"
            elif kind in CONNECTION_TESTS:
                job.status = "succeeded" if result.get("success") is True else "failed"
                job.error = (
                    ""
                    if result.get("success") is True
                    else result.get("message", "Bağlantı testi başarısız.")
                )
            elif kind == "identify":
                count = len(result.get("fields", {}))
                job.status = "succeeded" if count == 3 else "partial" if count else "failed"
                job.error = "" if count == 3 else "Okunamayan alanlarda mevcut bilgiler korundu."
            elif kind == "discovery" and result.get("unresponsive"):
                job.status = "partial" if result["reachable"] else "failed"
            else:
                job.status = "succeeded"
            job.result, job.finished_at, job.active_key = result, now(), None
            db.commit()
    except Exception as exc:
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if isinstance(exc, Cancelled):
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
                if isinstance(exc, Cancelled)
                else str(exc)
                if isinstance(exc, BackupError)
                else "Cihaz işlemi başarısız. Kapsam, erişim profili, protokol ve host anahtarını kontrol edin."
            )
            if kind in KINDS and not isinstance(exc, Cancelled):
                job.error = (
                    "Entegrasyon okunamadı. Sunucu, TLS güveni, kullanıcı/parola ve salt okunur API/WinRM yetkilerini kontrol edin."
                    if kind == "integration"
                    else "IPAM işlemi başarısız. Yetkili kapsamı, güncel port eşleşmesini ve DNS/SNMP/ICMP erişimini kontrol edin."
                )
            if kind in ("backup", "compare") and not isinstance(exc, Cancelled):
                code, job.error = backup_failure(exc)
                job.result = {**job.result, "error_code": code}
            if job.status != "queued":
                job.active_key, job.finished_at = None, now()
            db.commit()
            log.warning("job_failed job_id=%s error_class=%s", job_id, type(exc).__name__)
    finally:
        if not task.done():
            task.cancel()
        publish()


def heartbeat(role):
    try:
        redis_client().set(f"netrix:{role}:heartbeat", now().isoformat(), ex=90)
    except Exception:
        pass


async def worker_loop():
    while not stop:
        heartbeat("worker")
        try:
            job = claim(interactive=False)
            if job:
                await execute(job)
            else:
                await asyncio.sleep(2)
        except Exception as exc:
            log.warning("worker_cycle_failed error_class=%s", type(exc).__name__)
            await asyncio.sleep(5)


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
