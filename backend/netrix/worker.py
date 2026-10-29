import asyncio
import hashlib
import ipaddress
import logging
import signal
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from . import models as m
from .alerting.engine import evaluate
from .core import now, redis_client, session_factory
from .discovery.correlation import correlate
from .discovery.protocols import NetworkError, SNMPCollector, fetch_config
from .identity.security import encrypt, secret_data
from .monitoring.rates import calculate_rate
from .services import authorized_device, get, in_scope, publish

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
        row.name: row for row in db.scalars(select(m.Interface).where(m.Interface.device_id == device.id))
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
        db.flush()
        counters = port.get("counters")
        if counters:
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


def persist_collection(db, device, collected, job):
    prior = db.scalar(
        select(m.Observation)
        .where(m.Observation.device_id == device.id)
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
    evidence["port_candidates"] = correlate(collected.get("tables", {}), collected.get("neighbors", []))
    db.add(
        m.Observation(
            job_id=job.id, device_id=device.id, address=device.management_ip, evidence=evidence, confidence=1
        )
    )
    sync_interfaces(db, device, collected, job.id)
    device.reachability, device.last_seen_at = "reachable", now()
    for neighbor in collected.get("neighbors", []):
        query = select(m.Link).where(
            m.Link.device_id == device.id,
            m.Link.interface_name == neighbor["interface_name"],
            m.Link.remote_name == neighbor["remote_name"],
            m.Link.remote_port == neighbor["remote_port"],
        )
        link = db.scalar(query)
        if not link:
            link = m.Link(device_id=device.id, **neighbor)
            db.add(link)
            db.add(
                m.Event(
                    device_id=device.id,
                    kind="link_observed",
                    message=f"{device.name}: {neighbor['source'].upper()} komşusu gözlemlendi",
                    details={"remote_name": neighbor["remote_name"]},
                )
            )
        # A unique advertised name is only a candidate, never proof of a physical link.
        candidates = list(
            db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id == device.vrf_id,
                    m.Device.id != device.id,
                    m.Device.name == neighbor["remote_name"],
                )
            )
        )
        link.confidence = 0.65 if len(candidates) == 1 else 0.5
        link.remote_device_id = candidates[0].id if len(candidates) == 1 else None
        link.updated_at = now()
    evaluate(db, device, "availability", 1)
    evaluate(db, device, "no_data", 0)


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
                persist_collection(db, device, collected, job)
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
        credential = get(
            db,
            m.Credential,
            device.config_credential_id if job.kind == "backup" else device.snmp_credential_id,
        )
        secret = secret_data(credential)
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
            if not data.strip():
                raise NetworkError("Cihaz boş konfigürasyon döndürdü")
            previous = db.scalar(
                select(m.Snapshot)
                .where(m.Snapshot.device_id == current.id)
                .order_by(m.Snapshot.created_at.desc())
                .limit(1)
            )
            fingerprint = hashlib.sha256(data.encode()).hexdigest()
            changed = previous is not None and previous.fingerprint != fingerprint
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
            persist_collection(db, current, data, job)
            current.last_monitor_at = now()
        job.progress, job.total = 1, 1
        db.commit()
        publish()
    return {"saved": True}


def claim():
    with session_factory()() as db:
        stale = list(
            db.scalars(
                select(m.Job)
                .where(m.Job.status == "running", m.Job.heartbeat_at < now() - timedelta(seconds=90))
                .with_for_update(skip_locked=True)
            )
        )
        for job in stale:
            job.status = "cancelled" if job.cancel_requested else "failed" if job.attempts >= 3 else "queued"
            job.error = "Worker bağlantısı kesildi; görev yeniden ele alındı"
            if job.status in ("failed", "cancelled"):
                job.active_key, job.finished_at = None, now()
        db.flush()
        job = db.scalar(
            select(m.Job)
            .where(m.Job.status == "queued", m.Job.available_at <= now())
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


async def execute(job_id, collector=None):
    collector = collector or SNMPCollector()
    with session_factory()() as db:
        kind = get(db, m.Job, job_id).kind
    task = asyncio.create_task(
        discover(job_id, collector) if kind == "discovery" else collect_device(job_id, collector)
    )
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=5)
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                job.heartbeat_at = now()
                cancelled = job.cancel_requested
                db.commit()
            heartbeat("worker")
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
            elif job.attempts < 3 and isinstance(
                exc, (NetworkError, OSError, TimeoutError, OperationalError)
            ):
                job.status = "queued"
                job.available_at = now() + timedelta(seconds=15 * 2 ** (job.attempts - 1))
            else:
                job.status = "failed"
            job.error = (
                "Görev iptal edildi"
                if isinstance(exc, Cancelled)
                else "Cihaz işlemi başarısız. Kapsam, erişim profili, protokol ve host anahtarını kontrol edin."
            )
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
            job = claim()
            if job:
                await execute(job)
            else:
                await asyncio.sleep(2)
        except Exception as exc:
            log.warning("worker_cycle_failed error_class=%s", type(exc).__name__)
            await asyncio.sleep(5)


def request_stop(*args):
    global stop
    stop = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    asyncio.run(worker_loop())
