"""Explicit manual reconciliation: SQL facts only, no protocol clients or ICMP."""

from datetime import timedelta

from sqlalchemy import or_, select

from .. import models as m
from ..core import now, session_factory
from ..runtime_limits import sql_read, sql_write
from ..services import in_scope, publish
from ..sources import records
from . import pipeline, service, teaming
from .connections import Evidence


class SQLContext:
    def __init__(self, db, vlan, job_id):
        self.vlan, self.job_id = vlan, job_id
        self.evidence = Evidence(db, {vlan.vrf_id})
        self.integrations = {
            i.id for i in db.scalars(select(m.Integration).where(m.Integration.enabled.is_(True)))
        }

    def check(self):
        from ..worker import Cancelled

        with session_factory()() as db:
            job = db.get(m.Job, self.job_id)
            vlan = db.get(m.VLAN, self.vlan.id)
            if (
                not job
                or job.cancel_requested
                or not vlan
                or (vlan.cidr, vlan.vrf_id, vlan.dns_server_id)
                != (self.vlan.cidr, self.vlan.vrf_id, self.vlan.dns_server_id)
            ):
                raise Cancelled()

    def for_row(self, row):
        return SQLSources(row, self)


class SQLSources:
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
                d = self.context.evidence.devices.get(g.device_id)
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
        from .inventory_sources import attachment

        with session_factory()() as db:
            return attachment(db, self.row, self.context.vlan, mac, evidence=self.context.evidence)

    async def dhcp(self, address, mac):
        rows = []
        with session_factory()() as db:
            for fact in db.scalars(
                select(m.DHCPBinding).where(
                    m.DHCPBinding.present.is_(True),
                    m.DHCPBinding.source_key.in_(self.context.integrations),
                    or_(m.DHCPBinding.address == address, m.DHCPBinding.mac_address == mac),
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
        with session_factory()() as db:
            fact = db.scalar(
                select(m.DNSRecord).where(
                    m.DNSRecord.address_id == self.row.id,
                    m.DNSRecord.source_key == (self.context.vlan.dns_server_id or "system"),
                )
            )
            if fact and fact.hostname:
                self.ref("dns", fact, fact.source_key, fact.updated_at)
            return fact.hostname if fact else ""

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
        if self.row.nic_teaming:
            hostname = await self.dns(self.row.address)
            with session_factory()() as db:
                result = teaming.result(hostname, teaming.neighbors(db, self.row, hostname), stored=True)
        else:
            result = await pipeline.resolve(self.row.address, self, progress)
        for issue in result["issues"]:
            if issue["code"] == "identity_missing":
                issue["message"] = "SQL'de etkin gateway IP/MAC kaydı yok; cihaz sorgulanmadı."
            elif issue["code"] == "missing_hostname":
                issue["message"] = (
                    "SQL kaynaklarından güncel hostname doğrulanamadı; varsa önceki doğrulanmış ad korunur."
                )
        result["values"]["observations"] = []
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

    started = now()

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
                        m.GatewayBinding.device_id.in_(context.evidence.devices),
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
            ids = list(
                db.scalars(
                    select(m.IPAddress.id)
                    .where(
                        m.IPAddress.vlan_id == vlan.id,
                        m.IPAddress.vrf_id == vlan.vrf_id,
                    )
                    .order_by(m.IPAddress.address)
                )
            )
            job.total, job.progress = len(ids), 0
            job.result = {**job.result, "scan_phase": "sql", "network": {"mode": "sql", "devices": 0}}
            db.commit()
        return vlan, scope, ids

    vlan, scope, ids = await sql_write(prepare)
    problems = resolved = 0
    for id in ids:
        context.check()
        with session_factory()() as db:
            row = db.get(m.IPAddress, id)
            if (
                not row
                or row.vlan_id != vlan.id
                or row.vrf_id != vlan.vrf_id
                or not in_scope(row.address, scope)
            ):
                continue
        result = await context.for_row(row).resolve()

        def save(row, result):
            nonlocal resolved, problems
            with session_factory()() as db:
                job = db.get(m.Job, job_id)
                current = db.get(m.IPAddress, id)
                if job.cancel_requested:
                    raise Cancelled()
                if not current or (current.address, current.vrf_id, current.vlan_id) != (
                    row.address,
                    row.vrf_id,
                    row.vlan_id,
                ):
                    return False
                pipeline.save_result(db, current, started, result)
                done = resolved + 1
                issues = problems + (result["status"] == "problem")
                job.progress = done
                job.result = {**job.result, "resolved": done, "problems": issues}
                db.commit()
                resolved, problems = done, issues
                return True

        if not await sql_write(save, row, result):
            continue
        publish(ipam_vlan=vlan.id)

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
