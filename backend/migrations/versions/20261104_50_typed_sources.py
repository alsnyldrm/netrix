"""Canonical typed source facts and DNS/SQL NIC-Teaming (verified move, then cleanup)."""

import sqlalchemy as sa
from alembic import op
from netrix.core import UTCDateTime

revision = "20261104_50"
down_revision = "20261104_49"
branch_labels = None
depends_on = None


def create_table(name, *args, **kwargs):
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *args, **kwargs)


def create_index(name, table, *args, **kwargs):
    if name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, *args, **kwargs)


def upgrade():
    create_table(
        "vmware_networks",
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("external_key", sa.String(length=64), nullable=False),
        sa.Column("switch_id", sa.String(length=190), nullable=False),
        sa.Column("switch_name", sa.String(length=190), nullable=False),
        sa.Column("standard_switch", sa.String(length=190), nullable=False),
        sa.Column("portgroup_key", sa.String(length=190), nullable=False),
        sa.Column("name", sa.String(length=190), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "external_key", name="uq_vmware_network"),
    )
    create_table(
        "dhcp_bindings",
        sa.Column("integration_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("hostname", sa.String(length=190), nullable=False),
        sa.Column("reserved", sa.Boolean(), nullable=False),
        sa.Column("lease_state", sa.String(length=40), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "address", "mac_address", name="uq_dhcp_fact"),
    )
    create_index("ix_dhcp_mac", "dhcp_bindings", ["mac_address", "source_key"], unique=False)
    create_table(
        "vmware_hosts",
        sa.Column("integration_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("external_id", sa.String(length=190), nullable=False),
        sa.Column("hostname", sa.String(length=190), nullable=False),
        sa.Column("uuid", sa.String(length=190), nullable=False),
        sa.Column("operating_system", sa.String(length=190), nullable=False),
        sa.Column("power_state", sa.String(length=40), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "external_id", name="uq_vmware_host"),
    )
    create_table(
        "vmware_physical_nics",
        sa.Column("host_id", sa.String(length=36), nullable=False),
        sa.Column("device", sa.String(length=120), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("link_up", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["vmware_hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_id", "device", name="uq_vmware_pnic"),
    )
    create_index(op.f("ix_vmware_physical_nics_host_id"), "vmware_physical_nics", ["host_id"], unique=False)
    create_table(
        "vmware_vms",
        sa.Column("integration_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("external_id", sa.String(length=190), nullable=False),
        sa.Column("host_id", sa.String(length=36), nullable=True),
        sa.Column("hostname", sa.String(length=190), nullable=False),
        sa.Column("operating_system", sa.String(length=190), nullable=False),
        sa.Column("power_state", sa.String(length=40), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["vmware_hosts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "external_id", name="uq_vmware_vm"),
    )
    create_index(op.f("ix_vmware_vms_host_id"), "vmware_vms", ["host_id"], unique=False)
    create_table(
        "vmware_nics",
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("owner_key", sa.String(length=190), nullable=False),
        sa.Column("nic_key", sa.String(length=120), nullable=False),
        sa.Column("vm_id", sa.String(length=36), nullable=True),
        sa.Column("host_id", sa.String(length=36), nullable=True),
        sa.Column("network_id", sa.String(length=36), nullable=True),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("port", sa.String(length=120), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("(vm_id IS NULL) <> (host_id IS NULL)", name="ck_vmware_nic_owner"),
        sa.ForeignKeyConstraint(["host_id"], ["vmware_hosts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["network_id"], ["vmware_networks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vm_id"], ["vmware_vms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "owner_key", "nic_key", name="uq_vmware_nic"),
    )
    create_index(op.f("ix_vmware_nics_host_id"), "vmware_nics", ["host_id"], unique=False)
    create_index(op.f("ix_vmware_nics_vm_id"), "vmware_nics", ["vm_id"], unique=False)
    create_table(
        "gateway_bindings",
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=190), nullable=False),
        sa.Column("source_name", sa.String(length=190), nullable=False),
        sa.Column("vrf_id", sa.String(length=36), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vrf_id"],
            ["vrfs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key", "vrf_id", "address", "mac_address", "if_index", name="uq_gateway_fact"
        ),
    )
    create_index(op.f("ix_gateway_bindings_device_id"), "gateway_bindings", ["device_id"], unique=False)
    create_index(op.f("ix_gateway_bindings_vrf_id"), "gateway_bindings", ["vrf_id"], unique=False)
    create_index("ix_gateway_ip", "gateway_bindings", ["vrf_id", "address"], unique=False)
    create_table(
        "network_source_states",
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=True),
        sa.Column("attempted_at", UTCDateTime(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.Column("error_class", sa.String(length=80), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("fdb_complete", sa.Boolean(), nullable=False),
        sa.Column("fdb_at", UTCDateTime(), nullable=True),
        sa.Column("gateway_at", UTCDateTime(), nullable=True),
        sa.Column("neighbors_at", UTCDateTime(), nullable=True),
        sa.Column("interfaces_at", UTCDateTime(), nullable=True),
        sa.Column("identity_at", UTCDateTime(), nullable=True),
        sa.Column("lldp_complete", sa.Boolean(), nullable=False),
        sa.Column("cdp_complete", sa.Boolean(), nullable=False),
        sa.Column("neighbor_detail_failed", sa.String(length=80), nullable=False),
        sa.Column("stp_port", sa.String(length=120), nullable=True),
        sa.Column("stp_root", sa.Boolean(), nullable=True),
        sa.Column("stp_source", sa.String(length=40), nullable=False),
        sa.Column("read_address", sa.String(length=45), nullable=False),
        sa.Column("read_port", sa.Integer(), nullable=True),
        sa.Column("read_vrf", sa.String(length=36), nullable=False),
        sa.Column("read_profile", sa.String(length=36), nullable=True),
        sa.Column("read_profile_at", sa.String(length=40), nullable=False),
        sa.Column("read_adapter", sa.String(length=40), nullable=False),
        sa.Column("read_config_port", sa.Integer(), nullable=True),
        sa.Column("read_trust", sa.Boolean(), nullable=False),
        sa.Column("read_ssh_profile", sa.String(length=36), nullable=True),
        sa.Column("read_ssh_at", sa.String(length=40), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    create_table(
        "vmware_addresses",
        sa.Column("nic_id", sa.String(length=36), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["nic_id"], ["vmware_nics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nic_id", "address", name="uq_vmware_address"),
    )
    create_index(op.f("ix_vmware_addresses_nic_id"), "vmware_addresses", ["nic_id"], unique=False)
    create_index("ix_vmware_ip", "vmware_addresses", ["address", "present"], unique=False)
    create_table(
        "vmware_nic_hints",
        sa.Column("physical_nic_id", sa.String(length=36), nullable=False),
        sa.Column("protocol", sa.String(length=8), nullable=False),
        sa.Column("chassis_id", sa.String(length=190), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("port_id", sa.String(length=120), nullable=False),
        sa.Column("port_description", sa.String(length=190), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["physical_nic_id"], ["vmware_physical_nics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index(
        op.f("ix_vmware_nic_hints_physical_nic_id"), "vmware_nic_hints", ["physical_nic_id"], unique=False
    )
    create_table(
        "vmware_uplinks",
        sa.Column("nic_id", sa.String(length=36), nullable=False),
        sa.Column("physical_nic_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["nic_id"], ["vmware_nics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["physical_nic_id"], ["vmware_physical_nics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("nic_id", "physical_nic_id"),
    )
    create_table(
        "device_source_identities",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("hostname", sa.String(length=190), nullable=False),
        sa.Column("sys_description", sa.Text(), nullable=False),
        sa.Column("sys_object_id", sa.String(length=190), nullable=False),
        sa.Column("uptime", sa.String(length=190), nullable=False),
        sa.Column("ip_forwarding", sa.String(length=10), nullable=False),
        sa.Column("vendor", sa.String(length=190), nullable=False),
        sa.Column("model", sa.String(length=190), nullable=False),
        sa.Column("serial", sa.String(length=190), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("software_version", sa.String(length=190), nullable=False),
        sa.Column("location", sa.String(length=190), nullable=False),
        sa.Column("system_name", sa.String(length=190), nullable=False),
        sa.Column("vendor_source", sa.String(length=40), nullable=False),
        sa.Column("model_source", sa.String(length=40), nullable=False),
        sa.Column("kind_source", sa.String(length=40), nullable=False),
        sa.Column("software_version_source", sa.String(length=40), nullable=False),
        sa.Column("serial_source", sa.String(length=40), nullable=False),
        sa.Column("system_name_source", sa.String(length=40), nullable=False),
        sa.Column("location_source", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_id"),
    )
    create_table(
        "discovery_reads",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("error_class", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("network_state_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.ForeignKeyConstraint(["network_state_id"], ["network_source_states.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "address"),
    )
    create_index(op.f("ix_discovery_reads_device_id"), "discovery_reads", ["device_id"], unique=False)
    create_index(op.f("ix_discovery_reads_job_id"), "discovery_reads", ["job_id"], unique=False)
    create_index(
        op.f("ix_discovery_reads_network_state_id"), "discovery_reads", ["network_state_id"], unique=False
    )
    create_table(
        "gateway_networks",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("prefix_length", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_id", "if_index", "address", "prefix_length", name="uq_gateway_network"),
    )
    create_index(op.f("ix_gateway_networks_state_id"), "gateway_networks", ["state_id"], unique=False)
    create_table(
        "mac_port_records",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("vrf_id", sa.String(length=36), nullable=False),
        sa.Column("vlan_vid", sa.Integer(), nullable=False),
        sa.Column("fdb_id", sa.Integer(), nullable=False),
        sa.Column("bridge_port", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("port", sa.String(length=190), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vrf_id"],
            ["vrfs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "fdb_id", "mac_address", "port", name="uq_mac_port_fact"),
    )
    create_index(
        "ix_mac_port_lookup", "mac_port_records", ["vrf_id", "vlan_vid", "mac_address"], unique=False
    )
    create_index(op.f("ix_mac_port_records_snapshot_id"), "mac_port_records", ["snapshot_id"], unique=False)
    create_table(
        "source_bridge_ports",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("bridge_port", sa.Integer(), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_id", "bridge_port"),
    )
    create_table(
        "source_ports",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=190), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("alias", sa.String(length=400), nullable=False),
        sa.Column("mac_address", sa.String(length=40), nullable=False),
        sa.Column("admin_status", sa.String(length=20), nullable=False),
        sa.Column("oper_status", sa.String(length=20), nullable=False),
        sa.Column("speed_bps", sa.BigInteger(), nullable=True),
        sa.Column("aggregate", sa.String(length=120), nullable=False),
        sa.Column("aggregate_type", sa.String(length=40), nullable=False),
        sa.Column("aggregate_source", sa.String(length=40), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_id", "if_index", name="uq_source_port_index"),
    )
    create_index(op.f("ix_source_ports_state_id"), "source_ports", ["state_id"], unique=False)
    create_table(
        "source_unsupported_tables",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_id", "name"),
    )
    create_table(
        "source_vlan_fdb",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("vlan_vid", sa.Integer(), nullable=False),
        sa.Column("fdb_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_id", "vlan_vid"),
    )
    create_table(
        "vmware_hint_addresses",
        sa.Column("hint_id", sa.String(length=36), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.ForeignKeyConstraint(["hint_id"], ["vmware_nic_hints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hint_id", "address"),
    )
    create_table(
        "dns_records",
        sa.Column("address_id", sa.String(length=36), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("hostname", sa.String(length=190), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["ip_addresses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_id", "source_key", name="uq_dns_record"),
    )
    create_index(op.f("ix_dns_records_address_id"), "dns_records", ["address_id"], unique=False)
    create_table(
        "ip_resolution_results",
        sa.Column("address_id", sa.String(length=36), nullable=False),
        sa.Column("scope_address", sa.String(length=45), nullable=False),
        sa.Column("scope_vrf", sa.String(length=36), nullable=False),
        sa.Column("scope_vlan", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("retained", sa.Boolean(), nullable=False),
        sa.Column("cached_import", sa.Boolean(), nullable=False),
        sa.Column("hostname_conflict", sa.Boolean(), nullable=False),
        sa.Column("connection_type", sa.String(length=40), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=False),
        sa.Column("last_success_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("status in ('success','problem')", name="ck_ip_result_status"),
        sa.ForeignKeyConstraint(["address_id"], ["ip_addresses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_id"),
    )
    create_table(
        "neighbor_links",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("port_id", sa.String(length=36), nullable=False),
        sa.Column("identity_key", sa.String(length=64), nullable=False),
        sa.Column("remote_device_id", sa.String(length=36), nullable=True),
        sa.Column("manual_remote_name", sa.String(length=190), nullable=True),
        sa.Column("manual_remote_port", sa.String(length=120), nullable=True),
        sa.Column("manual_remote_device_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_add_excluded", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["manual_remote_device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["port_id"],
            ["source_ports.id"],
        ),
        sa.ForeignKeyConstraint(
            ["remote_device_id"],
            ["devices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "port_id", "identity_key", name="uq_neighbor_identity"),
    )
    create_index(op.f("ix_neighbor_links_device_id"), "neighbor_links", ["device_id"], unique=False)
    create_index(op.f("ix_neighbor_links_is_current"), "neighbor_links", ["is_current"], unique=False)
    create_index(
        op.f("ix_neighbor_links_remote_device_id"), "neighbor_links", ["remote_device_id"], unique=False
    )
    create_table(
        "ping_states",
        sa.Column("address_id", sa.String(length=36), nullable=False),
        sa.Column("reachability", sa.String(length=20), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["ip_addresses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_id"),
    )
    create_table(
        "cdp_neighbors",
        sa.Column("link_id", sa.String(length=36), nullable=False),
        sa.Column("remote_name", sa.String(length=190), nullable=False),
        sa.Column("remote_port", sa.String(length=120), nullable=False),
        sa.Column("device_id", sa.String(length=190), nullable=False),
        sa.Column("device_id_hex", sa.String(length=380), nullable=False),
        sa.Column("port_id", sa.String(length=190), nullable=False),
        sa.Column("system_name", sa.String(length=190), nullable=False),
        sa.Column("management_address", sa.String(length=45), nullable=False),
        sa.Column("record_index", sa.String(length=190), nullable=False),
        sa.Column("transport", sa.String(length=30), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["neighbor_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link_id"),
    )
    create_table(
        "ip_resolution_connections",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("neighbor_id", sa.String(length=36), nullable=True),
        sa.Column("mac_port_id", sa.String(length=36), nullable=True),
        sa.Column("vmware_nic_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("primary_source", sa.String(length=40), nullable=False),
        sa.Column("endpoint_identity", sa.String(length=250), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "(neighbor_id IS NOT NULL) + (mac_port_id IS NOT NULL) + (vmware_nic_id IS NOT NULL) = 1",
            name="ck_resolution_connection_ref",
        ),
        sa.ForeignKeyConstraint(["mac_port_id"], ["mac_port_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["neighbor_id"], ["neighbor_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_id"], ["ip_resolution_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vmware_nic_id"], ["vmware_nics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_id", "mac_port_id", name="uq_resolution_mac_port"),
        sa.UniqueConstraint("result_id", "neighbor_id", name="uq_resolution_neighbor"),
        sa.UniqueConstraint("result_id", "vmware_nic_id", name="uq_resolution_vmware_nic"),
    )
    create_index(
        op.f("ix_ip_resolution_connections_mac_port_id"),
        "ip_resolution_connections",
        ["mac_port_id"],
        unique=False,
    )
    create_index(
        op.f("ix_ip_resolution_connections_neighbor_id"),
        "ip_resolution_connections",
        ["neighbor_id"],
        unique=False,
    )
    create_index(
        op.f("ix_ip_resolution_connections_result_id"),
        "ip_resolution_connections",
        ["result_id"],
        unique=False,
    )
    create_index(
        op.f("ix_ip_resolution_connections_vmware_nic_id"),
        "ip_resolution_connections",
        ["vmware_nic_id"],
        unique=False,
    )
    create_table(
        "ip_resolution_issues",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["ip_resolution_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id", "position"),
    )
    create_table(
        "ip_resolution_steps",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("at", UTCDateTime(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("label", sa.String(length=190), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["result_id"], ["ip_resolution_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id", "position"),
    )
    create_table(
        "ip_source_links",
        sa.Column("address_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("matched_by", sa.String(length=40), nullable=False),
        sa.Column("dns_id", sa.String(length=36), nullable=True),
        sa.Column("ping_id", sa.String(length=36), nullable=True),
        sa.Column("dhcp_id", sa.String(length=36), nullable=True),
        sa.Column("vmware_id", sa.String(length=36), nullable=True),
        sa.Column("gateway_id", sa.String(length=36), nullable=True),
        sa.Column("network_id", sa.String(length=36), nullable=True),
        sa.Column("scope_address", sa.String(length=45), nullable=False),
        sa.Column("scope_vrf", sa.String(length=36), nullable=False),
        sa.Column("scope_vlan", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["ip_addresses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dhcp_id"], ["dhcp_bindings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dns_id"], ["dns_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateway_bindings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["network_id"], ["network_source_states.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ping_id"], ["ping_states.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vmware_id"], ["vmware_addresses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_id", "source", "source_key"),
    )
    create_index(op.f("ix_ip_source_links_address_id"), "ip_source_links", ["address_id"], unique=False)
    create_table(
        "lldp_neighbors",
        sa.Column("link_id", sa.String(length=36), nullable=False),
        sa.Column("remote_name", sa.String(length=190), nullable=False),
        sa.Column("remote_port", sa.String(length=120), nullable=False),
        sa.Column("chassis_id", sa.String(length=190), nullable=False),
        sa.Column("chassis_subtype", sa.Integer(), nullable=True),
        sa.Column("port_id", sa.String(length=190), nullable=False),
        sa.Column("port_subtype", sa.Integer(), nullable=True),
        sa.Column("port_description", sa.String(length=190), nullable=False),
        sa.Column("system_name", sa.String(length=190), nullable=False),
        sa.Column("management_address", sa.String(length=45), nullable=False),
        sa.Column("local_port_id", sa.String(length=190), nullable=False),
        sa.Column("local_port_number", sa.String(length=120), nullable=False),
        sa.Column("record_index", sa.String(length=190), nullable=False),
        sa.Column("transport", sa.String(length=30), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["neighbor_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link_id"),
    )
    create_table(
        "ip_resolution_fields",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("source_link_id", sa.String(length=36), nullable=True),
        sa.Column("gateway_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateway_bindings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_id"], ["ip_resolution_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_link_id"], ["ip_source_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id", "field"),
    )
    create_index(
        op.f("ix_ip_resolution_fields_gateway_id"), "ip_resolution_fields", ["gateway_id"], unique=False
    )
    create_index(
        op.f("ix_ip_resolution_fields_source_link_id"),
        "ip_resolution_fields",
        ["source_link_id"],
        unique=False,
    )
    if "nic_teaming" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ip_addresses")}:
        op.add_column(
            "ip_addresses", sa.Column("nic_teaming", sa.Boolean(), server_default="0", nullable=False)
        )
    from netrix.sources.migrate_v1 import transfer_and_verify

    transfer_and_verify(op.get_bind())
    # Child tables first; verification above is mandatory and raises before any drop.
    for table in (
        "ipam_results",
        "ip_observations",
        "switch_mac_entries",
        "switch_mac_snapshots",
        "topology_links",
        "discovery_observations",
        "ipam_network_states",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)


def downgrade():
    raise RuntimeError(
        "Refuse lossy downgrade: canonical source migration has removed verified legacy copies"
    )
