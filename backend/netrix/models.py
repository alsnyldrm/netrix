from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core import Base, UTCDateTime, now
from .sources.proxy import DiscoveryPayload, NetworkPayload, Payload, ResultPayload


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
    ssh_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("role in ('super_admin','admin','operator','viewer')", name="ck_user_role"),
        CheckConstraint(
            "role <> 'super_admin' OR lower(email) = 'alisan.yildirim@fbu.edu.tr'",
            name="ck_user_super_admin_email",
        ),
    )


class UserAvatar(Base):
    __tablename__ = "user_avatars"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preset_id: Mapped[str | None] = mapped_column(String(40))
    image: Mapped[bytes | None] = mapped_column(LargeBinary)
    version: Mapped[str] = mapped_column(String(36))
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=now, onupdate=now)
    __table_args__ = (
        CheckConstraint(
            "(preset_id IS NULL AND image IS NOT NULL) OR (preset_id IS NOT NULL AND image IS NULL)",
            name="ck_user_avatar_source",
        ),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime(), index=True)


class Audit(Entity, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_created_at", text("created_at DESC"), "id"),)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary: Mapped[str] = mapped_column(String(400))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Institution(Entity, Base):
    __tablename__ = "institutions"
    name: Mapped[str] = mapped_column(String(190))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Site(Entity, Base):
    __tablename__ = "sites"
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Istanbul")
    floor_number: Mapped[str] = mapped_column(String(40), default="", server_default="")
    department_name: Mapped[str] = mapped_column(String(120), default="", server_default="")


class Cabinet(Entity, Base):
    __tablename__ = "cabinets"
    sub_site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), index=True)
    units: Mapped[int] = mapped_column(Integer, default=42, server_default="42")
    lock_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (
        CheckConstraint("units >= 1 AND units <= 60", name="ck_cabinet_units"),
        UniqueConstraint("sub_site_id", "name", name="uq_cabinet_room_number"),
    )
    name: Mapped[str] = mapped_column(String(120))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(400), default="")


class ModelImage(Entity, Base):
    __tablename__ = "model_images"
    vendor: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(500))
    __table_args__ = (UniqueConstraint("vendor", "model"),)


class RackPlacement(Entity, Base):
    __tablename__ = "rack_placements"
    cabinet_id: Mapped[str] = mapped_column(ForeignKey("cabinets.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), unique=True)
    start_unit: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60", name="ck_rack_position"
        ),
    )


class RackAccessory(Entity, Base):
    __tablename__ = "rack_accessories"
    cabinet_id: Mapped[str] = mapped_column(ForeignKey("cabinets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="brush_organizer")
    start_unit: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("kind = 'brush_organizer'", name="ck_rack_accessory_kind"),
        CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60",
            name="ck_rack_accessory_position",
        ),
    )


class PatchPanel(Entity, Base):
    __tablename__ = "patch_panels"
    cabinet_id: Mapped[str] = mapped_column(ForeignKey("cabinets.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    start_unit: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    port_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("cabinet_id", "name", name="uq_patch_panel_name"),
        CheckConstraint("kind in ('cat','fiber')", name="ck_patch_panel_kind"),
        CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60", name="ck_patch_panel_position"
        ),
        CheckConstraint("port_count >= 1 AND port_count <= 288", name="ck_patch_panel_count"),
    )


class PatchPort(Entity, Base):
    __tablename__ = "patch_ports"
    panel_id: Mapped[str] = mapped_column(ForeignKey("patch_panels.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(40))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    interface_id: Mapped[str | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL"), index=True
    )
    device_name: Mapped[str] = mapped_column(String(190), default="")
    port_name: Mapped[str] = mapped_column(String(120), default="")
    cable_model: Mapped[str] = mapped_column(String(30), default="")
    fiber_mode: Mapped[str] = mapped_column(String(12), default="", server_default="")
    peer_port_id: Mapped[str | None] = mapped_column(
        ForeignKey("patch_ports.id", name="fk_patch_peer_port", ondelete="SET NULL"), nullable=True
    )
    external_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    __table_args__ = (
        UniqueConstraint("peer_port_id", name="uq_patch_peer_port"),
        UniqueConstraint("panel_id", "number", name="uq_patch_port_number"),
        UniqueConstraint("panel_id", "position", name="uq_patch_port_position"),
        CheckConstraint("position >= 1 AND position <= 288", name="ck_patch_port_position"),
        CheckConstraint(
            "cable_model in ('','Cat5','Cat6','Cat7','OM3','OM4','Multimode MM','Singlemode SM')",
            name="ck_patch_cable_model",
        ),
        CheckConstraint("fiber_mode in ('','multimode','singlemode')", name="ck_patch_fiber_mode"),
    )


class OperatingSystem(Entity, Base):
    __tablename__ = "operating_systems"
    name: Mapped[str] = mapped_column(String(190), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")


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
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    cidr: Mapped[str | None] = mapped_column(String(49), nullable=True)
    vrf_id: Mapped[str | None] = mapped_column(ForeignKey("vrfs.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    dns_server_id: Mapped[str | None] = mapped_column(ForeignKey("dns_servers.id"), index=True)
    warning_threshold: Mapped[int] = mapped_column(Integer, default=80, server_default="80")
    ping_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ping_interval: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    discovery_interval: Mapped[int] = mapped_column(Integer, default=3600, server_default="3600")
    last_ping_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_discovery_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        UniqueConstraint("domain", "vid"),
        UniqueConstraint("vrf_id", "cidr"),
        CheckConstraint("warning_threshold >= 1 AND warning_threshold <= 100", name="ck_vlan_threshold"),
        CheckConstraint("ping_interval >= 10 AND discovery_interval >= 60", name="ck_vlan_intervals"),
        CheckConstraint("vid >= 1 AND vid <= 4094", name="ck_vlan_vid"),
    )


class IPAMScanGroup(Entity, Base):
    __tablename__ = "ipam_scan_groups"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    frequency: Mapped[str] = mapped_column(String(10))
    repeat_every: Mapped[int] = mapped_column(Integer, default=1)
    timezone: Mapped[str] = mapped_column(String(60), default="Europe/Istanbul")
    start_at: Mapped[object] = mapped_column(UTCDateTime())
    next_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    run_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint("frequency in ('daily','weekly','monthly')", name="ck_ipam_scan_frequency"),
        CheckConstraint("repeat_every >= 1 AND repeat_every <= 365", name="ck_ipam_scan_every"),
        CheckConstraint(
            "run_count >= 0 AND (run_limit IS NULL OR run_limit >= 1)", name="ck_ipam_scan_count"
        ),
        Index("ix_ipam_scan_due", "enabled", "next_run_at"),
    )


class IPAMScanMember(Base):
    __tablename__ = "ipam_scan_members"
    group_id: Mapped[str] = mapped_column(
        ForeignKey("ipam_scan_groups.id", ondelete="CASCADE"), primary_key=True
    )
    vlan_id: Mapped[str] = mapped_column(
        ForeignKey("vlans.id", ondelete="CASCADE"), primary_key=True, unique=True
    )


class IPAMScanRun(Entity, Base):
    __tablename__ = "ipam_scan_runs"
    group_id: Mapped[str] = mapped_column(ForeignKey("ipam_scan_groups.id", ondelete="CASCADE"), index=True)
    scheduled_for: Mapped[object] = mapped_column(UTCDateTime())
    generation: Mapped[int] = mapped_column(Integer)
    jobs: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("group_id", "generation", "scheduled_for", name="uq_ipam_scan_slot"),)


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
    discovery_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("discovery_scopes.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    management_ip: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    vendor: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    manual_identity_fields: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    software_version: Mapped[str] = mapped_column(String(120), default="", server_default="")
    kind: Mapped[str] = mapped_column(
        String(20), ForeignKey("device_types.code", name="fk_device_type"), default="other", index=True
    )
    # Keep FOR UPDATE confined to devices, without locking the shared type catalog.
    device_type: Mapped[DeviceType] = relationship(lazy="selectin")
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
    is_gateway: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    config_path: Mapped[str] = mapped_column(String(200), default="/api/config")
    identity_path: Mapped[str] = mapped_column(
        String(200), default="/api/system", server_default="/api/system"
    )
    backup_interval: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    backup_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("backup_groups.id"), nullable=True, index=True
    )
    backup_retention: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_backup_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    base_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("config_snapshots.id", name="fk_device_base_snapshot", use_alter=True), index=True
    )
    approved_config_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    config_approved_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    config_approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    __table_args__ = (
        UniqueConstraint("vrf_id", "management_ip"),
        CheckConstraint(
            "lifecycle_status in ('planned','active','maintenance','retired')", name="ck_device_status"
        ),
        CheckConstraint("backup_interval >= 0", name="ck_device_interval"),
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
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    auto_add_excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    __table_args__ = (UniqueConstraint("device_id", "name"), UniqueConstraint("device_id", "if_index"))


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
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    last_success_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "kind in ('vcenter','windows_dhcp')",
            name="ck_integration_kind",
        ),
        CheckConstraint("interval_seconds = 0 OR interval_seconds >= 60", name="ck_integration_interval"),
    )


class IPAddress(Entity, Base):
    __tablename__ = "ip_addresses"
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), index=True)
    sub_site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), index=True)
    address: Mapped[str] = mapped_column(String(45))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    vlan_id: Mapped[str] = mapped_column(ForeignKey("vlans.id"), index=True)
    interface_id: Mapped[str | None] = mapped_column(ForeignKey("interfaces.id"), nullable=True, index=True)
    hostname: Mapped[str] = mapped_column(String(190), default="")
    mac_address: Mapped[str] = mapped_column(String(17), default="", server_default="")
    operating_system: Mapped[str] = mapped_column(String(190), default="", server_default="")
    cabinet: Mapped[str] = mapped_column(String(120), default="", server_default="")
    location: Mapped[str] = mapped_column(String(190), default="", server_default="")
    is_gateway: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    nic_teaming: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    __table_args__ = (
        UniqueConstraint("vrf_id", "address"),
        CheckConstraint("status in ('reserved','active','deprecated')", name="ck_ip_status"),
    )


class IPObservation(Payload, Entity, Base):
    __tablename__ = "ip_source_links"
    address_id: Mapped[str] = mapped_column(ForeignKey("ip_addresses.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(120))
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    matched_by: Mapped[str] = mapped_column(String(40), default="")
    dns_id: Mapped[str | None] = mapped_column(
        ForeignKey("dns_records.id", ondelete="CASCADE"), nullable=True
    )
    ping_id: Mapped[str | None] = mapped_column(
        ForeignKey("ping_states.id", ondelete="CASCADE"), nullable=True
    )
    dhcp_id: Mapped[str | None] = mapped_column(
        ForeignKey("dhcp_bindings.id", ondelete="CASCADE"), nullable=True
    )
    vmware_id: Mapped[str | None] = mapped_column(
        ForeignKey("vmware_addresses.id", ondelete="CASCADE"), nullable=True
    )
    gateway_id: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_bindings.id", ondelete="CASCADE"), nullable=True
    )
    network_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_source_states.id", ondelete="CASCADE"), nullable=True
    )
    scope_address: Mapped[str] = mapped_column(String(45), default="")
    scope_vrf: Mapped[str] = mapped_column(String(36), default="")
    scope_vlan: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dns: Mapped["DNSRecord | None"] = relationship("DNSRecord", lazy="joined")
    ping: Mapped["PingState | None"] = relationship("PingState", lazy="joined")
    dhcp: Mapped["DHCPBinding | None"] = relationship("DHCPBinding", lazy="joined")
    vmware: Mapped["VMwareAddress | None"] = relationship("VMwareAddress", lazy="joined")
    gateway: Mapped["GatewayBinding | None"] = relationship("GatewayBinding", lazy="joined")
    network: Mapped["IPAMNetworkState | None"] = relationship("IPAMNetworkState", lazy="select")
    __table_args__ = (UniqueConstraint("address_id", "source", "source_key"),)


class IPAMResult(ResultPayload, Entity, Base):
    __tablename__ = "ip_resolution_results"
    address_id: Mapped[str] = mapped_column(ForeignKey("ip_addresses.id", ondelete="CASCADE"), unique=True)
    scope_address: Mapped[str] = mapped_column(String(45), default="")
    scope_vrf: Mapped[str] = mapped_column(String(36), default="")
    scope_vlan: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="problem")
    retained: Mapped[bool] = mapped_column(Boolean, default=False)
    cached_import: Mapped[bool] = mapped_column(Boolean, default=False)
    hostname_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    connection_type: Mapped[str] = mapped_column(String(40), default="")
    started_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    completed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    last_success_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    fields: Mapped[list["ResolutionField"]] = relationship(
        "ResolutionField", cascade="all, delete-orphan", lazy="selectin"
    )
    connection_rows: Mapped[list["ResolutionConnection"]] = relationship(
        "ResolutionConnection", cascade="all, delete-orphan", lazy="selectin"
    )
    issue_rows: Mapped[list["ResolutionIssue"]] = relationship(
        "ResolutionIssue", cascade="all, delete-orphan", lazy="selectin"
    )
    step_rows: Mapped[list["ResolutionStep"]] = relationship(
        "ResolutionStep", cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (CheckConstraint("status in ('success','problem')", name="ck_ip_result_status"),)


class IPAMNetworkState(NetworkPayload, Entity, Base):
    __tablename__ = "network_source_states"
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    address: Mapped[str] = mapped_column(String(45), default="")
    observed_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True, default=now)
    attempted_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    error_class: Mapped[str] = mapped_column(String(80), default="")
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    fdb_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    fdb_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    gateway_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    neighbors_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    interfaces_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    identity_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    lldp_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    cdp_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    neighbor_detail_failed: Mapped[str] = mapped_column(String(80), default="")
    stp_port: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stp_root: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stp_source: Mapped[str] = mapped_column(String(40), default="")
    read_address: Mapped[str] = mapped_column(String(45), default="")
    read_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_vrf: Mapped[str] = mapped_column(String(36), default="")
    read_profile: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read_profile_at: Mapped[str] = mapped_column(String(40), default="")
    read_adapter: Mapped[str] = mapped_column(String(40), default="")
    read_config_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_trust: Mapped[bool] = mapped_column(Boolean, default=False)
    read_ssh_profile: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read_ssh_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ports: Mapped[list["SourcePort"]] = relationship(
        "SourcePort", cascade="all, delete-orphan", lazy="selectin", back_populates="state"
    )
    vlan_fdbs: Mapped[list["SourceVLANFDB"]] = relationship(
        "SourceVLANFDB", cascade="all, delete-orphan", lazy="selectin"
    )
    bridge_ports: Mapped[list["SourceBridgePort"]] = relationship(
        "SourceBridgePort", cascade="all, delete-orphan", lazy="selectin"
    )
    prefixes: Mapped[list["SourcePrefix"]] = relationship(
        "SourcePrefix", cascade="all, delete-orphan", lazy="selectin"
    )
    unsupported: Mapped[list["UnsupportedTable"]] = relationship(
        "UnsupportedTable", cascade="all, delete-orphan", lazy="selectin"
    )
    identity: Mapped["DeviceSourceIdentity | None"] = relationship(
        "DeviceSourceIdentity", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )
    mac_entries: Mapped[list["SwitchMacEntry"]] = relationship(
        "SwitchMacEntry", cascade="all, delete-orphan", lazy="select"
    )

    @property
    def read_context(self):
        return (
            [
                self.read_address,
                self.read_port,
                self.read_vrf,
                self.read_profile,
                self.read_profile_at,
                self.read_adapter,
                self.read_config_port,
                self.read_trust,
                self.read_ssh_profile,
                self.read_ssh_at,
            ]
            if self.read_address
            else []
        )

    @read_context.setter
    def read_context(self, value):
        if not value:
            return
        if len(value) != 10:
            self.__dict__["_legacy_cache_context"] = value
            return
        (
            self.read_address,
            self.read_port,
            self.read_vrf,
            self.read_profile,
            self.read_profile_at,
            self.read_adapter,
            self.read_config_port,
            self.read_trust,
            self.read_ssh_profile,
            self.read_ssh_at,
        ) = value


class Scope(Entity, Base):
    __tablename__ = "discovery_scopes"
    vlan_vid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    cidr: Mapped[str] = mapped_column(String(49))
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"), index=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"), index=True)
    profiles: Mapped[list["ScopeCredential"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="ScopeCredential.position"
    )

    @property
    def credential_ids(self):
        return [profile.credential_id for profile in self.profiles] or [self.credential_id]

    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    exclusions: Mapped[list] = mapped_column(JSON, default=list)
    seeds: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        CheckConstraint("interval_seconds = 0 OR interval_seconds >= 300", name="ck_scope_interval"),
    )


class ScopeCredential(Base):
    __tablename__ = "discovery_scope_credentials"
    scope_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_scopes.id", ondelete="CASCADE"), primary_key=True
    )
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("scope_id", "position"),)


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


class FirmwareImage(Entity, Base):
    __tablename__ = "firmware_images"
    name: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[str] = mapped_column(String(120))
    models: Mapped[list] = mapped_column(JSON)
    original_name: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    expected_sha256: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="uploading", index=True)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        CheckConstraint("family in ('aos_s_54xx','aos_s_29xx','cx6100','hp1950')", name="ck_fw_image_family"),
        CheckConstraint("status in ('uploading','ready')", name="ck_fw_image_status"),
        CheckConstraint("size_bytes >= 0", name="ck_fw_image_size"),
    )


class FirmwareGroup(Entity, Base):
    __tablename__ = "firmware_groups"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")


class FirmwareMember(Base):
    __tablename__ = "firmware_group_members"
    group_id: Mapped[str] = mapped_column(
        ForeignKey("firmware_groups.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    __table_args__ = (UniqueConstraint("device_id", name="uq_firmware_member_device"),)


class FirmwarePlan(Entity, Base):
    __tablename__ = "firmware_plans"
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="check")
    steps: Mapped[list] = mapped_column(JSON)
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    available_at: Mapped[object] = mapped_column(UTCDateTime(), default=now, index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    force_stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        Index("ix_fw_plan_history_order", "created_at", "id"),
        CheckConstraint("concurrency between 1 and 10", name="ck_fw_plan_concurrency"),
        CheckConstraint("mode in ('check','stage','upgrade','activate','verify')", name="ck_fw_plan_mode"),
        CheckConstraint(
            "status in ('draft','queued','running','paused','ready','succeeded','cancelled')",
            name="ck_fw_plan_status",
        ),
    )


class FirmwareTarget(Entity, Base):
    __tablename__ = "firmware_targets"
    plan_id: Mapped[str] = mapped_column(ForeignKey("firmware_plans.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    image_id: Mapped[str] = mapped_column(ForeignKey("firmware_images.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(30), default="waiting")
    bank: Mapped[str] = mapped_column(String(12), default="auto")
    previous_bank: Mapped[str] = mapped_column(String(12), default="")
    previous_version: Mapped[str] = mapped_column(String(120), default="")
    verified_version: Mapped[str] = mapped_column(String(120), default="")
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("config_snapshots.id"))
    active_device: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    heartbeat_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str] = mapped_column(String(40), default="")
    error: Mapped[str] = mapped_column(String(400), default="")
    transfer_username: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    transfer_secret_hash: Mapped[str] = mapped_column(String(64), default="")
    transfer_name: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    transfer_expires_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    transfer_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    finished_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        UniqueConstraint("plan_id", "device_id", name="uq_fw_plan_device"),
        CheckConstraint("stage >= 0", name="ck_fw_target_stage"),
        CheckConstraint(
            "status in ('queued','running','checked','staged','succeeded','failed','attention','cancelled')",
            name="ck_fw_target_status",
        ),
    )


class FirmwareEvent(Base):
    __tablename__ = "firmware_events"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=now, onupdate=now)
    target_id: Mapped[str] = mapped_column(ForeignKey("firmware_targets.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    phase: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="info")
    command: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    finished_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (
        Index("ix_fw_event_target_order", "target_id", "id"),
        CheckConstraint(
            "status in ('info','started','succeeded','failed','sent')", name="ck_fw_event_status"
        ),
    )


class Observation(DiscoveryPayload, Entity, Base):
    __tablename__ = "discovery_reads"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    address: Mapped[str] = mapped_column(String(45))
    source: Mapped[str] = mapped_column(String(20), default="snmpv3")
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_class: Mapped[str] = mapped_column(String(80), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1)
    network_state_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_source_states.id", ondelete="SET NULL"), nullable=True, index=True
    )
    network_state: Mapped[IPAMNetworkState | None] = relationship(lazy="selectin")
    __table_args__ = (UniqueConstraint("job_id", "address"),)


class Link(Entity, Base):
    __tablename__ = "neighbor_links"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    port_id: Mapped[str] = mapped_column(ForeignKey("source_ports.id"))
    local_port: Mapped["SourcePort"] = relationship("SourcePort", lazy="joined")
    identity_key: Mapped[str] = mapped_column(String(64))
    remote_device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    manual_remote_name: Mapped[str | None] = mapped_column(String(190), nullable=True)
    manual_remote_port: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manual_remote_device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="lldp")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    auto_add_excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    lldp: Mapped["LLDPNeighbor | None"] = relationship(
        "LLDPNeighbor", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )
    cdp: Mapped["CDPNeighbor | None"] = relationship(
        "CDPNeighbor", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )
    __table_args__ = (UniqueConstraint("device_id", "port_id", "identity_key", name="uq_neighbor_identity"),)

    @hybrid_property
    def interface_name(self):
        return self.__dict__.get("_pending_interface_name", self.local_port.name if self.local_port else "")

    @interface_name.setter
    def interface_name(self, value):
        self.__dict__["_pending_interface_name"] = value
        from .sources.proxy import changed

        changed(self)

    @interface_name.expression
    def interface_name(cls):
        from .sources.models import SourcePort

        return (
            select(SourcePort.name)
            .where(SourcePort.id == cls.port_id)
            .correlate_except(SourcePort)
            .scalar_subquery()
        )

    @property
    def aggregate(self):
        return self.local_port.aggregate if self.local_port else ""

    @property
    def aggregate_type(self):
        return self.local_port.aggregate_type if self.local_port else ""

    @property
    def aggregate_source(self):
        return self.local_port.aggregate_source if self.local_port else ""

    @property
    def stp_root(self):
        return self.local_port.state.stp_root if self.local_port else None

    @property
    def stp_port(self):
        return self.local_port.state.stp_port if self.local_port else None

    @property
    def stp_source(self):
        return self.local_port.state.stp_source if self.local_port else ""

    @hybrid_property
    def remote_name(self):
        if "_pending_remote_name" in self.__dict__:
            return self.__dict__["_pending_remote_name"]
        return (
            self.lldp.remote_name
            if self.lldp
            else self.cdp.remote_name
            if self.cdp
            else self.manual_remote_name or ""
        )

    @remote_name.setter
    def remote_name(self, value):
        self.__dict__["_pending_remote_name"] = value
        from .sources.proxy import changed

        changed(self)

    @remote_name.expression
    def remote_name(cls):
        from .sources.models import CDPNeighbor, LLDPNeighbor

        return func.coalesce(
            select(LLDPNeighbor.remote_name)
            .where(LLDPNeighbor.link_id == cls.id)
            .correlate_except(LLDPNeighbor)
            .scalar_subquery(),
            select(CDPNeighbor.remote_name)
            .where(CDPNeighbor.link_id == cls.id)
            .correlate_except(CDPNeighbor)
            .scalar_subquery(),
            cls.manual_remote_name,
            "",
        )

    @hybrid_property
    def remote_port(self):
        if "_pending_remote_port" in self.__dict__:
            return self.__dict__["_pending_remote_port"]
        return (
            self.lldp.remote_port
            if self.lldp
            else self.cdp.remote_port
            if self.cdp
            else self.manual_remote_port or ""
        )

    @remote_port.setter
    def remote_port(self, value):
        self.__dict__["_pending_remote_port"] = value
        from .sources.proxy import changed

        changed(self)

    @remote_port.expression
    def remote_port(cls):
        from .sources.models import CDPNeighbor, LLDPNeighbor

        return func.coalesce(
            select(LLDPNeighbor.remote_port)
            .where(LLDPNeighbor.link_id == cls.id)
            .correlate_except(LLDPNeighbor)
            .scalar_subquery(),
            select(CDPNeighbor.remote_port)
            .where(CDPNeighbor.link_id == cls.id)
            .correlate_except(CDPNeighbor)
            .scalar_subquery(),
            cls.manual_remote_port,
            "",
        )

    @property
    def evidence(self):
        if "_pending_evidence" in self.__dict__:
            return self.__dict__["_pending_evidence"]
        from .sources.neighbors import read

        return read(self)

    @evidence.setter
    def evidence(self, value):
        self.__dict__["_pending_evidence"] = dict(value or {})
        from .sources.proxy import changed

        changed(self)


class Snapshot(Entity, Base):
    __tablename__ = "config_snapshots"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    encrypted_content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql", "mariadb"))
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("job_id", "device_id"),)


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
        CheckConstraint("metric = 'config_change'", name="ck_alert_metric"),
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
    __table_args__ = (Index("ix_change_events_created_at", text("created_at DESC"), "id"),)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(400))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))


class UserWorkspace(Base):
    __tablename__ = "user_workspaces"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_commands: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserSSHProfile(Entity, Base):
    __tablename__ = "user_ssh_profiles"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    encrypted_ssh: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_user_ssh_profile_name"),
        UniqueConstraint("id", "owner_id", name="uq_user_ssh_profile_owner"),
    )


class AccessGroup(Entity, Base):
    __tablename__ = "access_groups"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400), default="")
    ssh_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_access_group_owner_name"),
        UniqueConstraint("id", "owner_id", name="uq_access_group_identity_owner"),
        Index("ix_access_group_ssh_profile_owner", "ssh_profile_id", "owner_id"),
        ForeignKeyConstraint(
            ["ssh_profile_id", "owner_id"],
            ["user_ssh_profiles.id", "user_ssh_profiles.owner_id"],
            name="fk_access_group_ssh_owner",
        ),
    )


class AccessGroupDevice(Base):
    __tablename__ = "access_group_devices"
    group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    __table_args__ = (
        UniqueConstraint("owner_id", "device_id", name="uq_access_group_user_device"),
        Index("ix_access_group_device_owner", "group_id", "owner_id"),
        ForeignKeyConstraint(
            ["group_id", "owner_id"],
            ["access_groups.id", "access_groups.owner_id"],
            name="fk_access_group_device_owner",
            ondelete="CASCADE",
        ),
    )


class SwitchMacEntry(Entity, Base):
    __tablename__ = "mac_port_records"
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("network_source_states.id", ondelete="CASCADE"), index=True
    )
    vrf_id: Mapped[str] = mapped_column(ForeignKey("vrfs.id"))
    vlan_vid: Mapped[int] = mapped_column(Integer, default=0)
    fdb_id: Mapped[int] = mapped_column(Integer, default=0)
    bridge_port: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="3")
    mac_address: Mapped[str] = mapped_column(String(17))
    port: Mapped[str] = mapped_column(String(190))
    if_index: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("snapshot_id", "fdb_id", "mac_address", "port", name="uq_mac_port_fact"),
        Index("ix_mac_port_lookup", "vrf_id", "vlan_vid", "mac_address"),
    )


SwitchMacSnapshot = IPAMNetworkState
# Import at the end: source models refer to the shared entities above.
from .sources import events as source_events  # noqa: E402,F401
from .sources.models import (  # noqa: E402,F401
    CDPNeighbor,
    DeviceSourceIdentity,
    DHCPBinding,
    DNSRecord,
    GatewayBinding,
    LLDPNeighbor,
    PingState,
    ResolutionConnection,
    ResolutionField,
    ResolutionIssue,
    ResolutionStep,
    SourceBridgePort,
    SourcePort,
    SourcePrefix,
    SourceVLANFDB,
    UnsupportedTable,
    VMwareAddress,
    VMwareHint,
    VMwareHintAddress,
    VMwareHost,
    VMwareNetwork,
    VMwareNIC,
    VMwarePhysicalNIC,
    VMwareUplink,
    VMwareVM,
)
