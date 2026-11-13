"""Manual reconciliation: inventory SQL plus a targeted DNS query; no switch access."""

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from .. import models as m
from ..core import now, session_factory
from ..runtime_limits import sql_read, sql_write
from ..services import in_scope, publish
from ..sources import records
from . import adapters, pipeline, service
from .connections import Evidence, network_device


def vlan_inputs(vlan):
    return (vlan.cidr, vlan.vrf_id, vlan.dns_server_id, vlan.vid, vlan.domain, vlan.discovery_interval)


class SQLContext:
    def __init__(self, db, vlan, job_id, *, point=False):
        self.vlan, self.job_id = vlan, job_id
        self.point = point
        self.dns_server = db.get(m.DNSServer, vlan.dns_server_id) if vlan.dns_server_id else None
        self._evidence = None
        self.physical_lock = threading.Lock()
        # Identity reads need only the small device catalogue, not every FDB/port.
        self.devices = {
            d.id: d
            for d in db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id == vlan.vrf_id,
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    m.Device.lifecycle_status.in_(("active", "maintenance")),
                )
            )
            if network_device(d)
        }
        self.integrations = {
            i.id for i in db.scalars(select(m.Integration).where(m.Integration.enabled.is_(True)))
        }

    @property
    def evidence(self):
        if self._evidence is None:
            with session_factory()() as db:
                self._evidence = Evidence(db, {self.vlan.vrf_id})
                self._evidence._fallback_lock = threading.RLock()
        return self._evidence

    def check(self):
        from ..worker import Cancelled

        with session_factory()() as db:
            job = db.get(m.Job, self.job_id)
            vlan = db.get(m.VLAN, self.vlan.id)
            if not job or job.cancel_requested or not vlan or vlan_inputs(vlan) != vlan_inputs(self.vlan):
                raise Cancelled()

    def for_row(self, row):
        return SQLSources(row, self)


class SQLSources:
    inventory_fallback = True

    def __init__(self, row, context):
        self.row, self.context = row, context
        self.refs = []
        self.times = []

    def ref(self, kind, row, key, at):
        self.refs.append(dict(kind=kind, id=row.id, source_key=key, observed_at=at.isoformat()))
        self.times.append(at)

    async def gateway(self, address):
        matches = []
        with session_factory()() as db:
            for g in db.scalars(
                select(m.GatewayBinding).where(
                    m.GatewayBinding.vrf_id == self.row.vrf_id,
                    m.GatewayBinding.address == address,
                    m.GatewayBinding.present.is_(True),
                )
            ):
                d = self.context.devices.get(g.device_id)
                if not d or not (d.is_gateway or d.kind in ("router", "firewall")):
                    continue
                self.ref("gateway", g, g.source_key, g.observed_at)
                matches.append(
                    dict(
                        device_id=d.id,
                        device_name=d.name,
                        mac_address=g.mac_address,
                        observed_at=g.observed_at.isoformat(),
                        source="gateway",
                    )
                )
        macs = {r["mac_address"] for r in matches}
        if len(macs) > 1:
            raise ValueError("Conflicting SQL gateway identities")
        return dict(mac_address=next(iter(macs), ""), gateway_evidence=matches)

    async def vmware(self, address, mac):
        rows = []
        with session_factory()() as db:
            for fact in db.scalars(
                select(m.VMwareAddress)
                .join(m.VMwareNIC)
                .where(
                    m.VMwareAddress.present.is_(True),
                    m.VMwareAddress.address == address,
                    m.VMwareNIC.source_key.in_(self.context.integrations),
                )
            ):
                data = records.vmware_data(fact)
                data["address"] = fact.address
                rows.append(data)
                self.ref("vcenter", fact, pipeline_key(data), fact.observed_at)
        return rows

    async def physical(self, address, mac):
        from .inventory_sources import attachment, point_evidence

        def resolve():
            # Evidence indexes and fallback views are shared within this job.
            # Build them once while four asynchronous IP decisions can advance.
            with self.context.physical_lock, session_factory()() as db:
                evidence = (
                    point_evidence(db, self.row, self.context.vlan, mac)
                    if self.context.point
                    else self.context.evidence
                )
                if not self.context.point:
                    lifetime = timedelta(
                        seconds=max(300, min(self.context.vlan.discovery_interval * 2, 86400))
                    )
                    evidence._static_links(self.row.vrf_id, evidence.at - lifetime)
            # A slow fallback build must not hold up an already prepared primary
            # match for a different IP. Database sessions are never shared.
            with session_factory()() as db:
                return attachment(db, self.row, self.context.vlan, mac, evidence=evidence)

        return await sql_read(resolve)

    async def dhcp(self, address, mac):
        rows = []
        with session_factory()() as db:
            for fact in db.scalars(
                select(m.DHCPBinding).where(
                    m.DHCPBinding.present.is_(True),
                    m.DHCPBinding.source_key.in_(self.context.integrations),
                    or_(m.DHCPBinding.address == address, m.DHCPBinding.mac_address == mac)
                    if mac
                    else m.DHCPBinding.address == address,
                )
            ):
                data = {
                    k: getattr(fact, k)
                    for k in ("address", "mac_address", "hostname", "reserved", "lease_state")
                }
                data["integration_id"] = fact.source_key
                rows.append(data)
                # Conflicting lease rows participate in validation, not field ownership.
                if fact.address == address:
                    self.ref("windows_dhcp", fact, fact.source_key, fact.observed_at)
        return rows

    async def dns(self, address):
        async with asyncio.timeout(1):
            hostname = await adapters.reverse_dns(address, self.context.dns_server)
        self.dns_observation = dict(
            source="dns",
            source_key=self.context.vlan.dns_server_id or "system",
            observed_at=now().isoformat(),
            data=dict(hostname=hostname),
        )
        return hostname

    async def resolve(self, progress=None):
        self.context.check()
        from ..worker import Cancelled

        with session_factory()() as db:
            current = db.get(m.IPAddress, self.row.id)
            if not current or (current.address, current.vrf_id, current.vlan_id, current.nic_teaming) != (
                self.row.address,
                self.row.vrf_id,
                self.row.vlan_id,
                self.row.nic_teaming,
            ):
                raise Cancelled()
        result = await pipeline.resolve(self.row.address, self, progress)
        for issue in result["issues"]:
            if issue["code"] == "identity_missing":
                issue["message"] = "SQL'de etkin gateway IP/MAC kaydı yok; cihaz sorgulanmadı."
            elif issue["code"] == "missing_hostname":
                issue["message"] = (
                    "SQL kaynaklarından güncel hostname doğrulanamadı; varsa önceki doğrulanmış ad korunur."
                )
        result["values"]["observations"] = [self.dns_observation] if hasattr(self, "dns_observation") else []
        result["values"]["_sql_only"] = True
        result["values"]["_sql_refs"] = self.refs
        if any(t < now() - timedelta(hours=24) for t in self.times):
            result["issues"].append(
                dict(
                    source="sql",
                    code="stale_source",
                    message="SQL kaynak kayıtlarının bazıları 24 saatten eski; cihaz sorgulanmadı.",
                )
            )
            result["status"] = "problem"
        self.context.check()
        return result


def pipeline_key(data):
    from ..sources.resolutions import source_key

    return source_key("vcenter", data, 0)


async def scan_vlan(job_id):
    from ..worker import Cancelled

    def load():
        # Read-only and slow: never keep this snapshot open across a job row write.
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            vlan = db.get(m.VLAN, job.target_id)
            if not vlan or job.cancel_requested:
                raise Cancelled()
            return SQLContext(db, vlan, job_id)

    context = await sql_read(load)

    def prepare():
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            vlan = db.get(m.VLAN, job.target_id)
            if not vlan or job.cancel_requested:
                raise Cancelled()
            scope = service.scan_boundary(db, vlan)
            # Import only addresses already present in canonical SQL sources, inside
            # this VLAN. No probing and no invented reachability state.
            from ..services import lock_vrf

            lock_vrf(db, vlan.vrf_id)
            stored = set(
                db.scalars(
                    select(m.GatewayBinding.address).where(
                        m.GatewayBinding.vrf_id == vlan.vrf_id,
                        m.GatewayBinding.present.is_(True),
                        m.GatewayBinding.device_id.in_(context.devices),
                    )
                )
            )
            stored.update(
                db.scalars(
                    select(m.DHCPBinding.address).where(
                        m.DHCPBinding.source_key.in_(context.integrations),
                        m.DHCPBinding.present.is_(True),
                    )
                )
            )
            stored.update(
                db.scalars(
                    select(m.VMwareAddress.address)
                    .join(m.VMwareNIC)
                    .where(
                        m.VMwareNIC.source_key.in_(context.integrations),
                        m.VMwareAddress.present.is_(True),
                    )
                )
            )
            existing = set(db.scalars(select(m.IPAddress.address).where(m.IPAddress.vrf_id == vlan.vrf_id)))
            import ipaddress

            subnet = ipaddress.ip_network(vlan.cidr)
            for address in sorted(stored - existing):
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if not in_scope(address, scope) or (
                    subnet.version == 4
                    and subnet.prefixlen < 31
                    and ip in (subnet.network_address, subnet.broadcast_address)
                ):
                    continue
                db.add(m.IPAddress(address=address, vrf_id=vlan.vrf_id, vlan_id=vlan.id))
            db.flush()
            targets = list(
                db.execute(
                    select(m.IPAddress.id, m.IPAddress.address, m.IPAddress.nic_teaming)
                    .where(m.IPAddress.vlan_id == vlan.id, m.IPAddress.vrf_id == vlan.vrf_id)
                    .order_by(m.IPAddress.address)
                )
            )
            targets.sort(
                key=lambda item: (ipaddress.ip_address(item[1]).version, int(ipaddress.ip_address(item[1])))
            )
            # Resume only the same job and unchanged inputs. A new explicit job
            # always gets a new start boundary. No second per-IP result is kept.
            signature = hashlib.sha256(
                json.dumps(
                    [
                        vlan.cidr,
                        vlan.vid,
                        vlan.domain,
                        vlan.discovery_interval,
                        vlan.vrf_id,
                        vlan.dns_server_id,
                        # Keep the existing input signature independent of execution order:
                        # an in-flight job resumes without replaying committed IPs.
                        [list(t) for t in sorted(targets, key=lambda item: item[1])],
                        sorted(context.integrations),
                        sorted(
                            (
                                d.id,
                                d.kind,
                                d.is_gateway,
                                d.discovery_scope_id,
                                d.snmp_credential_id,
                                d.config_credential_id,
                                d.management_ip,
                                d.adapter,
                                d.snmp_port,
                                d.config_port,
                                d.ssh_trust_host_key,
                            )
                            for d in context.devices.values()
                        ),
                        sorted(
                            (id, at.isoformat())
                            for id, at in db.execute(select(m.Credential.id, m.Credential.updated_at))
                        ),
                        [
                            (id, at.isoformat())
                            for id, at in db.execute(
                                select(m.Integration.id, m.Integration.updated_at).order_by(m.Integration.id)
                            )
                        ],
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            previous = job.result or {}
            same_inputs = previous.get("sql_signature", signature) == signature
            started = (
                datetime.fromisoformat(
                    previous.get("sql_started_at") or previous.get("started_at") or job.created_at.isoformat()
                )
                if same_inputs
                else now()
            )
            # Legacy in-flight jobs also resume from their existing current SQL
            # results. Scope checks prevent reuse after an address/VRF/VLAN move.
            completed = {
                r.address_id: r.status
                for r in db.execute(
                    select(m.IPAMResult.address_id, m.IPAMResult.status)
                    .join(m.IPAddress, m.IPAddress.id == m.IPAMResult.address_id)
                    .where(
                        m.IPAddress.vlan_id == vlan.id,
                        m.IPAMResult.scope_address == m.IPAddress.address,
                        m.IPAMResult.scope_vrf == m.IPAddress.vrf_id,
                        m.IPAMResult.scope_vlan == m.IPAddress.vlan_id,
                        m.IPAMResult.started_at >= started,
                        m.IPAMResult.cached_import.is_(False),
                    )
                )
            }
            ids = [id for id, _, _ in targets if id not in completed]
            resolved = len(targets) - len(ids)
            problems = sum(status == "problem" for status in completed.values())
            job.total, job.progress = len(targets), resolved
            job.result = {
                **previous,
                "scan_phase": "sql",
                "network": {"mode": "sql", "devices": 0},
                "sql_started_at": started.isoformat(),
                "sql_signature": signature,
                "resolved": resolved,
                "problems": problems,
            }
            db.commit()
        return vlan, scope, ids, started, resolved, problems

    vlan, scope, ids, started, resolved, problems = await sql_write(prepare)

    def save(row, result):
        nonlocal resolved, problems
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            current = db.get(m.IPAddress, row.id)
            current_vlan = db.get(m.VLAN, vlan.id)
            if job.cancel_requested or not current_vlan or vlan_inputs(current_vlan) != vlan_inputs(vlan):
                raise Cancelled()
            if not current or (current.address, current.vrf_id, current.vlan_id, current.nic_teaming) != (
                row.address,
                row.vrf_id,
                row.vlan_id,
                row.nic_teaming,
            ):
                raise Cancelled()
            # A newer explicit IP result wins; counting the decision as complete
            # must never overwrite that result with this older VLAN job.
            written = pipeline.save_result(db, current, started, result)
            status = result["status"]
            if not written:
                status = db.scalar(
                    select(m.IPAMResult.status).where(
                        m.IPAMResult.address_id == row.id,
                        m.IPAMResult.scope_address == row.address,
                        m.IPAMResult.scope_vrf == row.vrf_id,
                        m.IPAMResult.scope_vlan == row.vlan_id,
                        m.IPAMResult.started_at > started,
                    )
                )
                if status is None:
                    raise Cancelled()
            done = resolved + 1
            issues = problems + (status == "problem")
            job.progress = done
            job.result = {**job.result, "resolved": done, "problems": issues}
            db.commit()
            resolved, problems = done, issues

    async def process(id):
        with session_factory()() as db:
            row = db.get(m.IPAddress, id)
            if (
                not row
                or row.vlan_id != vlan.id
                or row.vrf_id != vlan.vrf_id
                or not in_scope(row.address, scope)
            ):
                raise Cancelled()
        result = await context.for_row(row).resolve()
        await sql_write(save, row, result)
        publish(ipam_vlan=vlan.id)

    # Numeric batches: each IP commits/notifies immediately, but the next four
    # do not start until every decision in the current batch has finished.
    for start in range(0, len(ids), 4):
        tasks = [asyncio.create_task(process(id)) for id in ids[start : start + 4]]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def finish():
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            job.result = {**job.result, "scan_phase": "complete"}
            db.commit()

    await sql_write(finish)
    return dict(
        checked=resolved,
        resolved=resolved,
        problems=problems,
        source_failed=int(problems > 0),
        network=dict(mode="sql", devices=0, read=0, failed=0),
    )
