"""Bounded, read-only widget data from each module's owned records."""

from datetime import timedelta

from sqlalchemy import and_, case, func, select

from . import models as m
from .core import now
from .discovery.visibility import inventory_links


def widget_data(db):
    def count(model, *conditions):
        return select(func.count()).select_from(model).where(*conditions).scalar_subquery()

    active = (
        m.Device.archived.is_(False),
        m.Device.discovery_scope_id.is_not(None),
        m.Device.lifecycle_status == "active",
    )
    operational_jobs = (m.Job.kind != "ipam_ping", m.Job.archived_at.is_(None))
    ip_scope = and_(
        m.IPAMResult.scope_address == m.IPAddress.address,
        m.IPAMResult.scope_vrf == m.IPAddress.vrf_id,
        m.IPAMResult.scope_vlan == m.IPAddress.vlan_id,
    )

    def ip_count(status):
        return (
            select(func.count())
            .select_from(m.IPAMResult)
            .join(m.IPAddress, m.IPAddress.id == m.IPAMResult.address_id)
            .where(ip_scope, m.IPAMResult.status == status)
            .scalar_subquery()
        )

    recent = m.Job.finished_at >= now() - timedelta(hours=24)
    counts = {
        "unverified": count(m.Device, *active, m.Device.reachability != "reachable"),
        "unplaced": count(m.Device, *active, m.Device.site_id.is_(None)),
        "no_backup": count(
            m.Device,
            *active,
            m.Device.config_credential_id.is_not(None),
            ~select(m.Snapshot.id).where(m.Snapshot.device_id == m.Device.id).exists(),
        ),
        "scopes": count(m.Scope, m.Scope.enabled.is_(True)),
        "credentials": count(m.Credential),
        "no_cidr": count(m.VLAN, m.VLAN.cidr.is_(None)),
        "ip_problems": ip_count("problem"),
        "ip_resolved": ip_count("success"),
        **{
            f"alarm_{severity}": count(m.Alert, m.Alert.state == "firing", m.Alert.severity == severity)
            for severity in ("critical", "warning", "info")
        },
        "scan_groups": count(m.IPAMScanGroup, m.IPAMScanGroup.enabled.is_(True)),
        "integrations": count(m.Integration, m.Integration.enabled.is_(True)),
        "links": count(
            m.Link, m.Link.is_current.is_(True), m.Link.auto_add_excluded.is_(False), inventory_links()
        ),
        "queued": count(m.Job, *operational_jobs, m.Job.status == "queued"),
        "running": count(m.Job, *operational_jobs, m.Job.status == "running"),
        **{
            status: count(m.Job, *operational_jobs, recent, m.Job.status == status)
            for status in ("succeeded", "partial", "failed")
        },
        "firmware_plans": count(
            m.FirmwarePlan,
            m.FirmwarePlan.deleted_at.is_(None),
            m.FirmwarePlan.status.in_(("queued", "running", "paused")),
        ),
        "firmware_attention": (
            select(func.count())
            .select_from(m.FirmwareTarget)
            .join(m.FirmwarePlan, m.FirmwarePlan.id == m.FirmwareTarget.plan_id)
            .where(m.FirmwarePlan.deleted_at.is_(None), m.FirmwareTarget.status == "attention")
            .scalar_subquery()
        ),
        "firmware_images": count(m.FirmwareImage, m.FirmwareImage.status == "ready"),
        "rules": count(m.AlertRule, m.AlertRule.enabled.is_(True)),
    }
    alerts = db.execute(
        select(m.Alert.id, m.Alert.message, m.Alert.severity, m.Alert.created_at, m.Alert.acknowledged_at)
        .where(m.Alert.state == "firing")
        .order_by(
            m.Alert.acknowledged_at.is_not(None),
            case({"critical": 0, "warning": 1}, value=m.Alert.severity, else_=2),
            m.Alert.created_at.desc(),
            m.Alert.id,
        )
        .limit(5)
    ).mappings()
    events = db.execute(
        select(m.Event.id, m.Event.message, m.Event.created_at)
        .order_by(m.Event.created_at.desc(), m.Event.id)
        .limit(5)
    ).mappings()
    return {
        "counts": dict(db.execute(select(*(value.label(key) for key, value in counts.items()))).one()._mapping),
        "alerts": [dict(row) for row in alerts],
        "events": [dict(row) for row in events],
        "server_time": now(),
    }
