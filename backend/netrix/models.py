from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .core import Base, UTCDateTime, now


def uid():
    return str(uuid4())


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=now, onupdate=now)


class User(Entity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(190), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("role in ('admin','operator','viewer')", name="ck_user_role"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime(), index=True)


class Audit(Entity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary: Mapped[str] = mapped_column(String(400))


class Site(Entity, Base):
    __tablename__ = "sites"
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Istanbul")


class VRF(Entity, Base):
    __tablename__ = "vrfs"
    lock_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")


class VLAN(Entity, Base):
    __tablename__ = "vlans"
    name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[str] = mapped_column(String(80), default="default")
    vid: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("domain", "vid"),
        CheckConstraint("vid >= 1 AND vid <= 4094", name="ck_vlan_vid"),
    )


class Credential(Entity, Base):
    __tablename__ = "credentials"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    protocol: Mapped[str] = mapped_column(String(20))
    encrypted_secret: Mapped[str] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("protocol in ('snmpv3','ssh','rest')", name="ck_credential_protocol"),)


class Device(Entity, Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(120))
    management_ip: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    vendor: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(20), default="other")
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active")
    reachability: Mapped[str] = mapped_column(String(20), default="unknown")
    adapter: Mapped[str] = mapped_column(String(20), default="ios")
    snmp_credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("credentials.id"), nullable=True, index=True
    )
    config_credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("credentials.id"), nullable=True, index=True
    )
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    config_port: Mapped[int] = mapped_column(Integer, default=22)
    config_path: Mapped[str] = mapped_column(String(200), default="/api/config")
    identity_path: Mapped[str] = mapped_column(
        String(200), default="/api/system", server_default="/api/system"
    )
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monitor_interval: Mapped[int] = mapped_column(Integer, default=300)
    backup_interval: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_monitor_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_backup_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        UniqueConstraint("vrf_id", "management_ip"),
        CheckConstraint(
            "lifecycle_status in ('planned','active','maintenance','retired')", name="ck_device_status"
        ),
        CheckConstraint("monitor_interval >= 60 AND backup_interval >= 0", name="ck_device_interval"),
    )


class Interface(Entity, Base):
    __tablename__ = "interfaces"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    if_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mac_address: Mapped[str] = mapped_column(String(40), default="")
    speed_bps: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    oper_status: Mapped[str] = mapped_column(String(20), default="unknown")
    description: Mapped[str] = mapped_column(String(400), default="")
    __table_args__ = (UniqueConstraint("device_id", "name"), UniqueConstraint("device_id", "if_index"))


class Prefix(Entity, Base):
    __tablename__ = "prefixes"
    cidr: Mapped[str] = mapped_column(String(49))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    vlan_id: Mapped[str | None] = mapped_column(ForeignKey("vlans.id"), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    __table_args__ = (UniqueConstraint("vrf_id", "cidr"),)


class IPAddress(Entity, Base):
    __tablename__ = "ip_addresses"
    address: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    prefix_id: Mapped[str] = mapped_column(ForeignKey("prefixes.id"), index=True)
    interface_id: Mapped[str | None] = mapped_column(ForeignKey("interfaces.id"), nullable=True, index=True)
    hostname: Mapped[str] = mapped_column(String(190), default="")
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    __table_args__ = (
        UniqueConstraint("vrf_id", "address"),
        CheckConstraint("status in ('reserved','active','deprecated')", name="ck_ip_status"),
    )


class Scope(Entity, Base):
    __tablename__ = "discovery_scopes"
    name: Mapped[str] = mapped_column(String(120))
    cidr: Mapped[str] = mapped_column(String(49))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    exclusions: Mapped[list] = mapped_column(JSON, default=list)
    seeds: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint("interval_seconds = 0 OR interval_seconds >= 300", name="ck_scope_interval"),
    )


class Job(Entity, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    active_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(200), default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    available_at: Mapped[object] = mapped_column(UTCDateTime(), default=now, index=True)
    finished_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status in ('queued','running','succeeded','partial','failed','cancelled')", name="ck_job_status"
        ),
    )


class Observation(Entity, Base):
    __tablename__ = "discovery_observations"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    address: Mapped[str] = mapped_column(String(45))
    source: Mapped[str] = mapped_column(String(20), default="snmpv3")
    __table_args__ = (UniqueConstraint("job_id", "address"),)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1)


class Link(Entity, Base):
    __tablename__ = "topology_links"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    interface_name: Mapped[str] = mapped_column(String(120))
    remote_name: Mapped[str] = mapped_column(String(190))
    remote_port: Mapped[str] = mapped_column(String(120))
    remote_device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20), default="lldp")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    __table_args__ = (UniqueConstraint("device_id", "interface_name", "remote_name", "remote_port"),)


class Snapshot(Entity, Base):
    __tablename__ = "config_snapshots"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    encrypted_content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql", "mariadb"))
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("job_id", "device_id"),)


class Sample(Entity, Base):
    __tablename__ = "interface_samples"
    interface_id: Mapped[str] = mapped_column(ForeignKey("interfaces.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    in_octets: Mapped[int] = mapped_column(Numeric(20, 0))
    out_octets: Mapped[int] = mapped_column(Numeric(20, 0))
    in_errors: Mapped[int] = mapped_column(Numeric(20, 0), default=0)
    out_errors: Mapped[int] = mapped_column(Numeric(20, 0), default=0)
    in_discards: Mapped[int] = mapped_column(Numeric(20, 0), default=0)
    out_discards: Mapped[int] = mapped_column(Numeric(20, 0), default=0)
    uptime_ticks: Mapped[int] = mapped_column(Numeric(20, 0))
    discontinuity_ticks: Mapped[int] = mapped_column(Numeric(20, 0), default=0)
    speed_bps: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[str] = mapped_column(String(30), default="baseline")
    __table_args__ = (
        Index("ix_samples_interface_time", "interface_id", "created_at"),
        Index("ix_samples_retention_time", "created_at"),
        UniqueConstraint("job_id", "interface_id"),
    )


class AlertRule(Entity, Base):
    __tablename__ = "alert_rules"
    name: Mapped[str] = mapped_column(String(120))
    metric: Mapped[str] = mapped_column(String(30))
    threshold: Mapped[float] = mapped_column(Float, default=80)
    recovery_threshold: Mapped[float] = mapped_column(Float, default=70)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint(
            "metric in ('availability','utilization','config_change','no_data')", name="ck_alert_metric"
        ),
        CheckConstraint("severity in ('info','warning','critical')", name="ck_alert_severity"),
    )


class Alert(Entity, Base):
    __tablename__ = "alert_instances"
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    active_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(400))
    observed_value: Mapped[float] = mapped_column(Float, default=0)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    acknowledged_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (CheckConstraint("state in ('pending','firing','resolved')", name="ck_alert_state"),)


class Event(Entity, Base):
    __tablename__ = "change_events"
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(400))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))
