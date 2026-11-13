"""One relational owner for every source fact. No serialized source payloads."""

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core import Base, UTCDateTime, now
from ..models import Entity

if TYPE_CHECKING:
    from ..models import IPAMNetworkState, IPObservation, Link, SwitchMacEntry


class GatewayBinding(Entity, Base):
    __tablename__ = "gateway_bindings"
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("envanter.devices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_key: Mapped[str] = mapped_column(String(190))
    source_name: Mapped[str] = mapped_column(String(190), default="")
    vrf_id: Mapped[str] = mapped_column(ForeignKey("ip_adres_yonetimi.vrfs.id"), index=True)
    address: Mapped[str] = mapped_column(String(45))
    mac_address: Mapped[str] = mapped_column(String(17))
    if_index: Mapped[int] = mapped_column(Integer, default=0)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (
        UniqueConstraint(
            "source_key", "vrf_id", "address", "mac_address", "if_index", name="uq_gateway_fact"
        ),
        Index("ix_gateway_ip", "vrf_id", "address"),
    )


class DHCPBinding(Entity, Base):
    __tablename__ = "dhcp_bindings"
    integration_id: Mapped[str | None] = mapped_column(
        ForeignKey("yonetim.integrations.id", ondelete="CASCADE"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(45))
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    hostname: Mapped[str] = mapped_column(String(190), default="")
    reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_state: Mapped[str] = mapped_column(String(40), default="")
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (
        UniqueConstraint("source_key", "address", "mac_address", name="uq_dhcp_fact"),
        Index("ix_dhcp_mac", "mac_address", "source_key"),
    )


class VMwareHost(Entity, Base):
    __tablename__ = "vmware_hosts"
    integration_id: Mapped[str | None] = mapped_column(
        ForeignKey("yonetim.integrations.id", ondelete="CASCADE"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str] = mapped_column(String(190))
    hostname: Mapped[str] = mapped_column(String(190), default="")
    uuid: Mapped[str] = mapped_column(String(190), default="")
    operating_system: Mapped[str] = mapped_column(String(190), default="")
    power_state: Mapped[str] = mapped_column(String(40), default="")
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    physical_nics: Mapped[list["VMwarePhysicalNIC"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (UniqueConstraint("source_key", "external_id", name="uq_vmware_host"),)


class VMwareVM(Entity, Base):
    __tablename__ = "vmware_vms"
    integration_id: Mapped[str | None] = mapped_column(
        ForeignKey("yonetim.integrations.id", ondelete="CASCADE"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str] = mapped_column(String(190))
    host_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    hostname: Mapped[str] = mapped_column(String(190), default="")
    operating_system: Mapped[str] = mapped_column(String(190), default="")
    power_state: Mapped[str] = mapped_column(String(40), default="")
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    host: Mapped[VMwareHost | None] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("source_key", "external_id", name="uq_vmware_vm"),)


class VMwareNetwork(Entity, Base):
    __tablename__ = "vmware_networks"
    source_key: Mapped[str] = mapped_column(String(120))
    external_key: Mapped[str] = mapped_column(String(64))
    switch_id: Mapped[str] = mapped_column(String(190), default="")
    switch_name: Mapped[str] = mapped_column(String(190), default="")
    standard_switch: Mapped[str] = mapped_column(String(190), default="")
    portgroup_key: Mapped[str] = mapped_column(String(190), default="")
    name: Mapped[str] = mapped_column(String(190), default="")
    __table_args__ = (UniqueConstraint("source_key", "external_key", name="uq_vmware_network"),)


class VMwareNIC(Entity, Base):
    __tablename__ = "vmware_nics"
    source_key: Mapped[str] = mapped_column(String(120))
    owner_key: Mapped[str] = mapped_column(String(190))
    nic_key: Mapped[str] = mapped_column(String(120))
    vm_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_vms.id", ondelete="CASCADE"), nullable=True, index=True
    )
    host_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_hosts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    network_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_networks.id", ondelete="SET NULL"), nullable=True
    )
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    port: Mapped[str] = mapped_column(String(120), default="")
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    vm: Mapped[VMwareVM | None] = relationship(lazy="joined")
    host: Mapped[VMwareHost | None] = relationship(lazy="joined")
    network: Mapped[VMwareNetwork | None] = relationship(lazy="joined")
    uplinks: Mapped[list["VMwareUplink"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("source_key", "owner_key", "nic_key", name="uq_vmware_nic"),
        CheckConstraint("(vm_id IS NULL) <> (host_id IS NULL)", name="ck_vmware_nic_owner"),
    )


class VMwareAddress(Entity, Base):
    __tablename__ = "vmware_addresses"
    nic_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_nics.id", ondelete="CASCADE"), index=True
    )
    address: Mapped[str] = mapped_column(String(45), default="")
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[object] = mapped_column(UTCDateTime(), default=now)
    nic: Mapped[VMwareNIC] = relationship(lazy="joined")
    __table_args__ = (
        UniqueConstraint("nic_id", "address", name="uq_vmware_address"),
        Index("ix_vmware_ip", "address", "present"),
    )


class VMwarePhysicalNIC(Entity, Base):
    __tablename__ = "vmware_physical_nics"
    host_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_hosts.id", ondelete="CASCADE"), index=True
    )
    device: Mapped[str] = mapped_column(String(120))
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    link_up: Mapped[bool] = mapped_column(Boolean, default=False)
    hints: Mapped[list["VMwareHint"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (UniqueConstraint("host_id", "device", name="uq_vmware_pnic"),)


class VMwareUplink(Base):
    __tablename__ = "vmware_uplinks"
    nic_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_nics.id", ondelete="CASCADE"), primary_key=True
    )
    physical_nic_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_physical_nics.id", ondelete="CASCADE"), primary_key=True
    )
    physical_nic: Mapped[VMwarePhysicalNIC] = relationship(lazy="joined")


class VMwareHint(Entity, Base):
    __tablename__ = "vmware_nic_hints"
    physical_nic_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_physical_nics.id", ondelete="CASCADE"), index=True
    )
    protocol: Mapped[str] = mapped_column(String(8))
    chassis_id: Mapped[str] = mapped_column(String(190), default="")
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("envanter.devices.id", ondelete="SET NULL"), nullable=True
    )
    port_id: Mapped[str] = mapped_column(String(120), default="")
    port_description: Mapped[str] = mapped_column(String(190), default="")
    addresses: Mapped[list["VMwareHintAddress"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class VMwareHintAddress(Base):
    __tablename__ = "vmware_hint_addresses"
    hint_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_nic_hints.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String(45), primary_key=True)


class DNSRecord(Entity, Base):
    __tablename__ = "dns_records"
    address_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_addresses.id", ondelete="CASCADE"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(120))
    hostname: Mapped[str] = mapped_column(String(190), default="")
    __table_args__ = (UniqueConstraint("address_id", "source_key", name="uq_dns_record"),)


class PingState(Entity, Base):
    __tablename__ = "ping_states"
    address_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_addresses.id", ondelete="CASCADE"), unique=True
    )
    reachability: Mapped[str] = mapped_column(String(20), default="unknown")


class LLDPNeighbor(Entity, Base):
    __tablename__ = "lldp_neighbors"
    link_id: Mapped[str] = mapped_column(
        ForeignKey("baglanti.neighbor_links.id", ondelete="CASCADE"), unique=True
    )
    remote_name: Mapped[str] = mapped_column(String(190), default="")
    remote_port: Mapped[str] = mapped_column(String(120), default="")
    chassis_id: Mapped[str] = mapped_column(String(190), default="")
    chassis_subtype: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_id: Mapped[str] = mapped_column(String(190), default="")
    port_subtype: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_description: Mapped[str] = mapped_column(String(190), default="")
    system_name: Mapped[str] = mapped_column(String(190), default="")
    management_address: Mapped[str] = mapped_column(String(45), default="")
    local_port_id: Mapped[str] = mapped_column(String(190), default="")
    local_port_number: Mapped[str] = mapped_column(String(120), default="")
    record_index: Mapped[str] = mapped_column(String(190), default="")
    transport: Mapped[str] = mapped_column(String(30), default="")


class CDPNeighbor(Entity, Base):
    __tablename__ = "cdp_neighbors"
    link_id: Mapped[str] = mapped_column(
        ForeignKey("baglanti.neighbor_links.id", ondelete="CASCADE"), unique=True
    )
    remote_name: Mapped[str] = mapped_column(String(190), default="")
    remote_port: Mapped[str] = mapped_column(String(120), default="")
    device_id: Mapped[str] = mapped_column(String(190), default="")
    device_id_hex: Mapped[str] = mapped_column(String(380), default="")
    port_id: Mapped[str] = mapped_column(String(190), default="")
    system_name: Mapped[str] = mapped_column(String(190), default="")
    management_address: Mapped[str] = mapped_column(String(45), default="")
    record_index: Mapped[str] = mapped_column(String(190), default="")
    transport: Mapped[str] = mapped_column(String(30), default="")


class SourcePort(Entity, Base):
    __tablename__ = "source_ports"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), index=True
    )
    if_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped["IPAMNetworkState"] = relationship(
        "IPAMNetworkState", back_populates="ports", lazy="select"
    )
    name: Mapped[str] = mapped_column(String(190), default="")
    description: Mapped[str] = mapped_column(String(400), default="")
    alias: Mapped[str] = mapped_column(String(400), default="")
    mac_address: Mapped[str] = mapped_column(String(40), default="")
    admin_status: Mapped[str] = mapped_column(String(20), default="unknown")
    oper_status: Mapped[str] = mapped_column(String(20), default="unknown")
    speed_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    aggregate: Mapped[str] = mapped_column(String(120), default="")
    aggregate_type: Mapped[str] = mapped_column(String(40), default="")
    aggregate_source: Mapped[str] = mapped_column(String(40), default="")
    __table_args__ = (UniqueConstraint("state_id", "if_index", name="uq_source_port_index"),)


class SourceVLANFDB(Base):
    __tablename__ = "source_vlan_fdb"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), primary_key=True
    )
    vlan_vid: Mapped[int] = mapped_column(Integer, primary_key=True)
    fdb_id: Mapped[int] = mapped_column(Integer)


class SourceBridgePort(Base):
    __tablename__ = "source_bridge_ports"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), primary_key=True
    )
    bridge_port: Mapped[int] = mapped_column(Integer, primary_key=True)
    if_index: Mapped[int] = mapped_column(Integer)


class SourcePrefix(Entity, Base):
    __tablename__ = "gateway_networks"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), index=True
    )
    if_index: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(45))
    prefix_length: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("state_id", "if_index", "address", "prefix_length", name="uq_gateway_network"),
    )


class UnsupportedTable(Base):
    __tablename__ = "source_unsupported_tables"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="unsupported")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    attempted_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    successful_at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)


class DeviceSourceIdentity(Base):
    __tablename__ = "device_source_identities"
    state_id: Mapped[str] = mapped_column(
        ForeignKey("envanter.network_source_states.id", ondelete="CASCADE"), primary_key=True
    )
    hostname: Mapped[str] = mapped_column(String(190), default="")
    sys_description: Mapped[str] = mapped_column(Text, default="")
    sys_object_id: Mapped[str] = mapped_column(String(190), default="")
    uptime: Mapped[str] = mapped_column(String(190), default="")
    ip_forwarding: Mapped[str] = mapped_column(String(10), default="")
    vendor: Mapped[str] = mapped_column(String(190), default="")
    model: Mapped[str] = mapped_column(String(190), default="")
    serial: Mapped[str] = mapped_column(String(190), default="")
    kind: Mapped[str] = mapped_column(String(40), default="")
    software_version: Mapped[str] = mapped_column(String(190), default="")
    location: Mapped[str] = mapped_column(String(190), default="")
    system_name: Mapped[str] = mapped_column(String(190), default="")

    vendor_source: Mapped[str] = mapped_column(String(40), default="")
    model_source: Mapped[str] = mapped_column(String(40), default="")
    kind_source: Mapped[str] = mapped_column(String(40), default="")
    software_version_source: Mapped[str] = mapped_column(String(40), default="")
    serial_source: Mapped[str] = mapped_column(String(40), default="")
    system_name_source: Mapped[str] = mapped_column(String(40), default="")
    location_source: Mapped[str] = mapped_column(String(40), default="")


class ResolutionField(Base):
    __tablename__ = "ip_resolution_fields"
    result_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_resolution_results.id", ondelete="CASCADE"), primary_key=True
    )
    field: Mapped[str] = mapped_column(String(30), primary_key=True)
    source_link_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_source_links.id", ondelete="CASCADE"), nullable=True, index=True
    )
    gateway_id: Mapped[str | None] = mapped_column(
        ForeignKey("envanter.gateway_bindings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    neighbor_id: Mapped[str | None] = mapped_column(
        ForeignKey("baglanti.neighbor_links.id", ondelete="CASCADE"), nullable=True, index=True
    )
    neighbor: Mapped["Link | None"] = relationship("Link", lazy="selectin")
    source: Mapped[str] = mapped_column(String(40), default="")
    source_link: Mapped["IPObservation | None"] = relationship("IPObservation", lazy="joined")
    gateway: Mapped[GatewayBinding | None] = relationship(lazy="joined")


class ResolutionConnection(Entity, Base):
    __tablename__ = "ip_resolution_connections"
    result_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_resolution_results.id", ondelete="CASCADE"), index=True
    )
    neighbor_id: Mapped[str | None] = mapped_column(
        ForeignKey("baglanti.neighbor_links.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mac_port_id: Mapped[str | None] = mapped_column(
        ForeignKey("envanter.mac_port_records.id", ondelete="CASCADE"), nullable=True, index=True
    )
    vmware_nic_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_adres_yonetimi.vmware_nics.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(40), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    primary_source: Mapped[str] = mapped_column(String(40), default="")
    endpoint_identity: Mapped[str] = mapped_column(String(250), default="")
    neighbor: Mapped["Link | None"] = relationship("Link", lazy="joined")
    mac_port: Mapped["SwitchMacEntry | None"] = relationship("SwitchMacEntry", lazy="joined")
    vmware_nic: Mapped[VMwareNIC | None] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN neighbor_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN mac_port_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN vmware_nic_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_resolution_connection_ref",
        ),
        UniqueConstraint("result_id", "neighbor_id", name="uq_resolution_neighbor"),
        UniqueConstraint("result_id", "mac_port_id", name="uq_resolution_mac_port"),
        UniqueConstraint("result_id", "vmware_nic_id", name="uq_resolution_vmware_nic"),
    )


class ResolutionIssue(Base):
    __tablename__ = "ip_resolution_issues"
    result_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_resolution_results.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)


class ResolutionStep(Base):
    __tablename__ = "ip_resolution_steps"
    result_id: Mapped[str] = mapped_column(
        ForeignKey("ip_adres_yonetimi.ip_resolution_results.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    at: Mapped[object | None] = mapped_column(UTCDateTime(), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="")
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("envanter.devices.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(190), default="")
