"""Make VLANs the IPAM owner and persist configuration baselines and approvals."""

import ipaddress
import uuid

import sqlalchemy as sa
from alembic import op

revision = "20261101_21"
down_revision = "20261101_20"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    blocks = list(db.execute(sa.text("SELECT * FROM prefixes")).mappings())
    owners = [p["vlan_id"] for p in blocks]
    if None in owners or len(owners) != len(set(owners)):
        raise RuntimeError("Before migration, each existing IP block must belong to a different VLAN")
    # Check before DDL. Existing IPs and VLAN identities are retained in place.
    for name, type_, default, nullable in (
        ("institution_id", sa.String(36), None, True),
        ("site_id", sa.String(36), None, True),
        ("vrf_id", sa.String(36), None, True),
        ("cidr", sa.String(49), None, True),
        ("dns_server_id", sa.String(36), None, True),
        ("description", sa.String(400), "", False),
        ("scan_authorized", sa.Boolean(), "1", False),
        ("warning_threshold", sa.Integer(), "80", False),
        ("ping_enabled", sa.Boolean(), "0", False),
        ("ping_interval", sa.Integer(), "300", False),
        ("discovery_enabled", sa.Boolean(), "0", False),
        ("discovery_interval", sa.Integer(), "3600", False),
        ("last_ping_at", sa.DateTime(), None, True),
        ("last_discovery_at", sa.DateTime(), None, True),
    ):
        op.add_column("vlans", sa.Column(name, type_, server_default=default, nullable=nullable))
    for column, table in (
        ("institution_id", "institutions"),
        ("site_id", "sites"),
        ("vrf_id", "vrfs"),
        ("dns_server_id", "dns_servers"),
    ):
        op.create_foreign_key("fk_vlan_" + column, "vlans", table, [column], ["id"])
        op.create_index("ix_vlans_" + column, "vlans", [column])
    op.create_unique_constraint("uq_vlan_network", "vlans", ["vrf_id", "cidr"])
    op.create_check_constraint(
        "ck_vlan_threshold", "vlans", "warning_threshold >= 1 AND warning_threshold <= 100"
    )
    op.create_check_constraint(
        "ck_vlan_intervals", "vlans", "ping_interval >= 30 AND discovery_interval >= 60"
    )
    moved = (
        "institution_id",
        "site_id",
        "vrf_id",
        "cidr",
        "dns_server_id",
        "description",
        "warning_threshold",
        "ping_enabled",
        "ping_interval",
        "discovery_enabled",
        "discovery_interval",
        "last_ping_at",
        "last_discovery_at",
    )
    for block in blocks:
        db.execute(
            sa.text("UPDATE vlans SET " + ", ".join(f"{k}=:{k}" for k in moved) + " WHERE id=:vlan_id"),
            dict(block),
        )
    op.add_column("ip_addresses", sa.Column("vlan_id", sa.String(36), nullable=True))
    db.execute(sa.text("UPDATE ip_addresses a JOIN prefixes p ON a.prefix_id=p.id SET a.vlan_id=p.vlan_id"))
    op.alter_column("ip_addresses", "vlan_id", existing_type=sa.String(36), nullable=False)
    op.create_foreign_key("fk_ip_vlan", "ip_addresses", "vlans", ["vlan_id"], ["id"])
    op.create_index("ix_ip_addresses_vlan_id", "ip_addresses", ["vlan_id"])
    for fk in sa.inspect(db).get_foreign_keys("ip_addresses"):
        if "prefix_id" in fk["constrained_columns"]:
            op.drop_constraint(fk["name"], "ip_addresses", type_="foreignkey")
    op.drop_column("ip_addresses", "prefix_id")
    # Convert pending work to the new owner; retire the removed inventory-to-IPAM job.
    db.execute(
        sa.text(
            "UPDATE jobs SET status='cancelled', active_key=NULL, cancel_requested=1 WHERE kind='ipam_inventory' AND status IN ('queued','running')"
        )
    )
    db.execute(sa.text("DELETE FROM jobs WHERE kind='ipam_inventory'"))
    for block in blocks:
        db.execute(
            sa.text(
                "UPDATE jobs SET target_id=:vlan, active_key=CASE WHEN active_key IS NULL THEN NULL ELSE CONCAT(kind, ':', :vlan) END WHERE target_id=:old AND kind IN ('ipam_ping','ipam_discover')"
            ),
            {"vlan": block["vlan_id"], "old": block["id"]},
        )
    op.drop_table("prefixes")
    op.drop_column("integrations", "prefix_ids")
    op.add_column("integrations", sa.Column("credential_id", sa.String(36), nullable=True))
    op.add_column("integrations", sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))
    op.create_foreign_key(
        "fk_integration_credential", "integrations", "credentials", ["credential_id"], ["id"]
    )
    op.create_index("ix_integrations_credential_id", "integrations", ["credential_id"])
    op.drop_constraint("ck_integration_kind", "integrations", type_="check")
    op.create_check_constraint(
        "ck_integration_kind",
        "integrations",
        "kind in ('vcenter','windows_dhcp','corner_switch','backbone_switch')",
    )
    op.add_column("discovery_scopes", sa.Column("vlan_vid", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("discovery_scope_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_device_discovery_scope",
        "devices",
        "discovery_scopes",
        ["discovery_scope_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_devices_discovery_scope_id", "devices", ["discovery_scope_id"])
    scopes = list(db.execute(sa.text("SELECT id,cidr,vrf_id FROM discovery_scopes")).mappings())
    for block in blocks:
        if block["scope_id"]:
            db.execute(
                sa.text(
                    "UPDATE discovery_scopes SET vlan_vid=(SELECT vid FROM vlans WHERE id=:vlan) WHERE id=:scope"
                ),
                {"vlan": block["vlan_id"], "scope": block["scope_id"]},
            )
    for device in db.execute(sa.text("SELECT id,management_ip,vrf_id FROM devices")).mappings():
        matches = [
            s
            for s in scopes
            if s["vrf_id"] == device["vrf_id"]
            and ipaddress.ip_address(device["management_ip"]) in ipaddress.ip_network(s["cidr"])
        ]
        if matches:
            db.execute(
                sa.text("UPDATE devices SET discovery_scope_id=:scope WHERE id=:id"),
                {"scope": matches[0]["id"], "id": device["id"]},
            )
    # Seed standalone IPAM sources from already configured switch endpoints once.
    # No reference to a discovery scope or device remains on these integrations.
    switches = list(
        db.execute(
            sa.text(
                "SELECT d.*, t.name AS type_name, c.encrypted_secret FROM devices d JOIN device_types t ON t.code=d.kind JOIN credentials c ON c.id=d.snmp_credential_id WHERE d.archived=0 AND c.protocol IN ('snmpv3','snmpv2c')"
            )
        ).mappings()
    )
    for device in switches:
        label = (device["type_name"] + " " + device["kind"]).lower()
        if "switch" not in label:
            continue
        kind = "backbone_switch" if "backbone" in label or "bakbone" in label else "corner_switch"
        db.execute(
            sa.text(
                "INSERT INTO integrations (id,created_at,updated_at,name,kind,host,port,encrypted_secret,enabled,verify_tls,interval_seconds,credential_id,evidence) VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,:name,:kind,:host,:port,:secret,1,1,600,:credential,'{}')"
            ),
            {
                "id": str(uuid.uuid4()),
                "name": ("IPAM · " + device["name"] + " · " + device["management_ip"])[:120],
                "kind": kind,
                "host": device["management_ip"],
                "port": device["snmp_port"],
                "secret": device["encrypted_secret"],
                "credential": device["snmp_credential_id"],
            },
        )
    # Old automatic inventory observations must not influence VLAN IPAM anymore.
    db.execute(sa.text("DELETE FROM ip_observations WHERE source='inventory'"))
    op.add_column("devices", sa.Column("base_snapshot_id", sa.String(36), nullable=True))
    op.add_column(
        "devices", sa.Column("approved_config_hash", sa.String(64), nullable=False, server_default="")
    )
    op.add_column("devices", sa.Column("config_approved_at", sa.DateTime(), nullable=True))
    op.add_column("devices", sa.Column("config_approved_by", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_device_base_snapshot", "devices", "config_snapshots", ["base_snapshot_id"], ["id"]
    )
    op.create_foreign_key("fk_device_config_approved_by", "devices", "users", ["config_approved_by"], ["id"])
    op.create_index("ix_devices_base_snapshot_id", "devices", ["base_snapshot_id"])
    op.create_index("ix_devices_config_approved_by", "devices", ["config_approved_by"])
    # Encryption keys stay in the application secret environment. No config is logged.
    from netrix import models as m
    from netrix.configuration.baselines import rebuild
    from sqlalchemy.orm import Session, load_only

    with Session(bind=db) as session:
        # Read only columns present at this revision, regardless of later model additions.
        for device in session.scalars(
            sa.select(m.Device).options(load_only(m.Device.id, m.Device.base_snapshot_id))
        ):
            rebuild(session, device)
        session.commit()


def downgrade():
    raise RuntimeError("VLAN ownership migration is permanent; do not recreate the removed block workflow")
