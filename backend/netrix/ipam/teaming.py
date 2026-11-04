"""Opt-in DNS -> canonical LLDP/CDP matching. Never contacts a switch or integration."""

from datetime import timedelta

from sqlalchemy import func, or_, select

from .. import models as m
from ..core import now, session_factory
from .service import normalized_hostname


def neighbors(db, row, hostname):
    name = normalized_hostname(hostname)
    if not name:
        return []
    fields = (
        m.Link.remote_name,
        m.Link.manual_remote_name,
        m.LLDPNeighbor.system_name,
        m.CDPNeighbor.system_name,
    )
    statement = (
        select(m.Link)
        .join(m.Device, m.Device.id == m.Link.device_id)
        .outerjoin(m.LLDPNeighbor, m.LLDPNeighbor.link_id == m.Link.id)
        .outerjoin(m.CDPNeighbor, m.CDPNeighbor.link_id == m.Link.id)
        .where(
            m.Device.vrf_id == row.vrf_id,
            m.Device.archived.is_(False),
            m.Device.lifecycle_status == "active",
            m.Device.discovery_scope_id.is_not(None),
            m.Link.is_current.is_(True),
            m.Link.auto_add_excluded.is_(False),
            m.Link.source.in_(("lldp", "cdp", "lldp+cdp", "cdp+lldp")),
            or_(*(func.lower(func.trim(f)).in_((name, name + ".")) for f in fields)),
        )
        .order_by(m.Link.device_id, m.Link.id)
    )
    found = {}
    for link in db.scalars(statement):
        if not link.interface_name:
            continue
        device = db.get(m.Device, link.device_id)
        at = link.last_seen_at or link.updated_at
        key = (link.device_id, link.interface_name)
        item = dict(
            device_id=link.device_id,
            device_name=device.name,
            port=link.interface_name,
            remote_port=link.remote_port,
            aggregate=link.aggregate,
            source="nic_teaming",
            confidence=link.confidence or 0.5,
            neighbor_id=link.id,
            protocol=link.source,
            observed_at=at.isoformat(),
        )
        if key not in found or found[key]["observed_at"] < item["observed_at"]:
            found[key] = item
    return list(found.values())


def result(hostname, connections, *, error=None, observation=None, stored=False):
    from .pipeline import groups

    issues = []
    if error:
        issues.append(
            dict(
                source="dns",
                code=type(error).__name__,
                message="NIC-Teaming: DNS kaynağı okunamadı; önceki doğrulanmış bağlantılar korundu.",
            )
        )
    elif not hostname:
        issues.append(
            dict(
                source="dns",
                code="missing_hostname",
                message="NIC-Teaming: DNS hostname bulunamadı; komşu adı tahmin edilmedi.",
            )
        )
    elif not connections:
        issues.append(
            dict(
                source="neighbors",
                code="attachment_missing",
                message="NIC-Teaming: DNS hostname ile eşleşen güncel LLDP/CDP komşuluk kaydı bulunamadı.",
            )
        )
    old = now() - timedelta(hours=24)
    from datetime import datetime

    if any(datetime.fromisoformat(c["observed_at"]) < old for c in connections):
        issues.append(
            dict(
                source="neighbors",
                code="stale_source",
                message="NIC-Teaming: listelenen komşuluk kayıtlarından bazıları 24 saatten eski; yeni switch sorgusu yapılmadı.",
            )
        )
    g = groups(connections)
    values = dict(
        hostname=hostname or "",
        mac_address="",
        operating_system="",
        network="",
        power_state="",
        connections=connections,
        connection_groups=g,
        connected_device=" / ".join(x["device_name"] for x in g),
        connected_port=" / ".join(x["port_label"] for x in g),
        connection_type="nic_teaming",
        gateway_evidence=[],
        field_sources={"hostname": "dns" if hostname else ""},
        observations=[observation] if observation else [],
        cached_import=stored,
    )
    steps = [
        dict(source=s, status="skipped_nic_teaming")
        for s in ("gateway", "vmware", "backbone", "switch", "dhcp")
    ]
    steps.extend(
        [
            dict(
                source="dns",
                status="error" if error else "ok",
                at=now().isoformat(),
                mode="stored" if stored else "query",
            ),
            dict(
                source="neighbors",
                status="ok" if connections else "missing",
                at=now().isoformat(),
                mode="stored",
            ),
        ]
    )
    return dict(status="problem" if issues else "success", values=values, issues=issues, steps=steps)


class TeamingSources:
    nic_teaming = True

    def __init__(self, row, vlan, job_id=None):
        self.row, self.vlan, self.job_id = row, vlan, job_id

    def check(self):
        from ..worker import Cancelled

        with session_factory()() as db:
            current = db.get(m.IPAddress, self.row.id)
            vlan = db.get(m.VLAN, self.vlan.id)
            job = db.get(m.Job, self.job_id) if self.job_id else None
            if (
                not current
                or not current.nic_teaming
                or [current.address, current.vrf_id, current.vlan_id]
                != [self.row.address, self.row.vrf_id, self.row.vlan_id]
                or not vlan
                or vlan.cidr != self.vlan.cidr
                or vlan.dns_server_id != self.vlan.dns_server_id
                or (job and job.cancel_requested)
            ):
                raise Cancelled()

    async def resolve(self, progress=None):
        from . import adapters

        self.check()
        if progress:
            await progress("dns")
        with session_factory()() as db:
            server = db.get(m.DNSServer, self.vlan.dns_server_id) if self.vlan.dns_server_id else None
        error = None
        try:
            hostname = await adapters.reverse_dns(self.row.address, server)
        except Exception as exc:
            hostname = ""
            error = exc
        self.check()
        if progress:
            await progress("neighbors")
        with session_factory()() as db:
            connections = neighbors(db, self.row, hostname)
        observation = (
            None
            if error
            else dict(
                source="dns",
                source_key=self.vlan.dns_server_id or "system",
                observed_at=now().isoformat(),
                data={"hostname": hostname},
            )
        )
        return result(hostname, connections, error=error, observation=observation)


def reconcile(db, row):
    """Editing the switch uses existing SQL only; it is not permission to run DNS."""
    from . import pipeline, service

    if not row.nic_teaming:
        existing = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == row.id))
        if existing and existing.connection_type == "nic_teaming":
            db.delete(existing)
        return
    vlan = db.get(m.VLAN, row.vlan_id)
    obs = service.observations(db, [row])[row.id]
    hostname = service.dns_hostname(obs, vlan)
    resolved = result(hostname, neighbors(db, row, hostname), stored=True)
    pipeline.save_result(db, row, now(), resolved)
