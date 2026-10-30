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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    __table_args__ = (
        CheckConstraint("protocol in ('snmpv3','snmpv2c','ssh','rest')", name="ck_credential_protocol"),
    )


class BackupGroup(Entity, Base):
    __tablename__ = "backup_groups"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    retention_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        CheckConstraint("interval_seconds = 0 OR interval_seconds >= 300", name="ck_backup_group_interval"),
        CheckConstraint("retention_count >= 0", name="ck_backup_group_retention"),
    )


class DeviceType(Entity, Base):
    __tablename__ = "device_types"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")


class Device(Entity, Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(120))
    management_ip: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    vendor: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    manual_identity_fields: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    kind: Mapped[str] = mapped_column(
        String(20), ForeignKey("device_types.code", name="fk_device_type"), default="other", index=True
    )
    device_type: Mapped[DeviceType] = relationship(lazy="joined")
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
    ssh_trust_host_key: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    config_path: Mapped[str] = mapped_column(String(200), default="/api/config")
    identity_path: Mapped[str] = mapped_column(
        String(200), default="/api/system", server_default="/api/system"
    )
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monitor_interval: Mapped[int] = mapped_column(Integer, default=300)
    backup_interval: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_monitor_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    backup_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("backup_groups.id"), nullable=True, index=True
    )
    backup_retention: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    auto_add_excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    __table_args__ = (UniqueConstraint("device_id", "name"), UniqueConstraint("device_id", "if_index"))


class Prefix(Entity, Base):
    __tablename__ = "prefixes"
    cidr: Mapped[str] = mapped_column(String(49))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    vlan_id: Mapped[str | None] = mapped_column(ForeignKey("vlans.id"), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    dns_server_id: Mapped[str | None] = mapped_column(ForeignKey("dns_servers.id"), index=True)
    vlan_device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), index=True)
    scope_id: Mapped[str | None] = mapped_column(ForeignKey("discovery_scopes.id"), index=True)
    warning_threshold: Mapped[int] = mapped_column(Integer, default=80, server_default="80")
    ping_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    ping_interval: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    discovery_interval: Mapped[int] = mapped_column(Integer, default=3600, server_default="3600")
    last_ping_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_discovery_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        UniqueConstraint("vrf_id", "cidr"),
        CheckConstraint("warning_threshold >= 1 AND warning_threshold <= 100", name="ck_prefix_threshold"),
        CheckConstraint("ping_interval >= 30 AND discovery_interval >= 60", name="ck_prefix_intervals"),
    )


class DNSServer(Entity, Base):
    __tablename__ = "dns_servers"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    address: Mapped[str] = mapped_column(String(45))
    port: Mapped[int] = mapped_column(Integer, default=53)


class Integration(Entity, Base):
    __tablename__ = "integrations"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    prefix_ids: Mapped[list] = mapped_column(JSON, default=list)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_success_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint("kind in ('vcenter','windows_dhcp')", name="ck_integration_kind"),
        CheckConstraint("interval_seconds = 0 OR interval_seconds >= 60", name="ck_integration_interval"),
    )


class IPAddress(Entity, Base):
    __tablename__ = "ip_addresses"
    address: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    prefix_id: Mapped[str] = mapped_column(ForeignKey("prefixes.id"), index=True)
    interface_id: Mapped[str | None] = mapped_column(ForeignKey("interfaces.id"), nullable=True, index=True)
    hostname: Mapped[str] = mapped_column(String(190), default="")
    operating_system: Mapped[str] = mapped_column(String(190), default="", server_default="")
    cabinet: Mapped[str] = mapped_column(String(120), default="", server_default="")
    location: Mapped[str] = mapped_column(String(190), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    __table_args__ = (
        UniqueConstraint("vrf_id", "address"),
        CheckConstraint("status in ('reserved','active','deprecated')", name="ck_ip_status"),
    )


class IPObservation(Entity, Base):
    __tablename__ = "ip_observations"
    address_id: Mapped[str] = mapped_column(ForeignKey("ip_addresses.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (UniqueConstraint("address_id", "source", "source_key"),)


class IPTraffic(Entity, Base):
    __tablename__ = "ip_traffic"
    address_id: Mapped[str] = mapped_column(ForeignKey("ip_addresses.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(120))
    sampled_at: Mapped[object] = mapped_column(UTCDateTime())
    interval_seconds: Mapped[int] = mapped_column(Integer)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (UniqueConstraint("address_id", "source_key", "sampled_at"),)


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
    manual_remote_name: Mapped[str | None] = mapped_column(String(190), nullable=True)
    manual_remote_port: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manual_remote_device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", name="fk_link_manual_remote_device"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), default="lldp")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    auto_add_excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
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
