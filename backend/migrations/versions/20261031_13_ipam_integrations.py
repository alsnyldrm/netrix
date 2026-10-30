"""IPAM policies, integration sources and endpoint observations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261031_13"
down_revision = "20261030_12"
branch_labels = None
depends_on = None


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
    ]


def upgrade():
    op.create_table(
        "dns_servers",
        *entity(),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("address", sa.String(45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
    )
    op.create_table(
        "integrations",
        *entity(),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("prefix_ids", sa.JSON(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_run_at", DATETIME(fsp=6)),
        sa.Column("last_success_at", DATETIME(fsp=6)),
        sa.CheckConstraint("kind in ('vcenter','windows_dhcp')", name="ck_integration_kind"),
        sa.CheckConstraint("interval_seconds = 0 OR interval_seconds >= 60", name="ck_integration_interval"),
    )
    for name, target in [
        ("dns_server_id", "dns_servers"),
        ("vlan_device_id", "devices"),
        ("scope_id", "discovery_scopes"),
    ]:
        op.add_column("prefixes", sa.Column(name, sa.String(36), nullable=True))
        op.create_foreign_key("fk_prefix_" + name, "prefixes", target, [name], ["id"])
        op.create_index("ix_prefixes_" + name, "prefixes", [name])
    for name, kind, default in [
        ("warning_threshold", sa.Integer(), "80"),
        ("ping_enabled", sa.Boolean(), "0"),
        ("ping_interval", sa.Integer(), "300"),
        ("discovery_enabled", sa.Boolean(), "0"),
        ("discovery_interval", sa.Integer(), "3600"),
    ]:
        op.add_column("prefixes", sa.Column(name, kind, nullable=False, server_default=default))
    for name in ("last_ping_at", "last_discovery_at"):
        op.add_column("prefixes", sa.Column(name, DATETIME(fsp=6), nullable=True))
    op.create_check_constraint(
        "ck_prefix_threshold", "prefixes", "warning_threshold >= 1 AND warning_threshold <= 100"
    )
    op.create_check_constraint(
        "ck_prefix_intervals", "prefixes", "ping_interval >= 30 AND discovery_interval >= 60"
    )
    for name, length in [("operating_system", 190), ("cabinet", 120), ("location", 190)]:
        op.add_column("ip_addresses", sa.Column(name, sa.String(length), nullable=False, server_default=""))
    op.create_table(
        "ip_observations",
        *entity(),
        sa.Column(
            "address_id", sa.String(36), sa.ForeignKey("ip_addresses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("observed_at", DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("address_id", "source", "source_key"),
    )
    op.create_index("ix_ip_observations_address_id", "ip_observations", ["address_id"])
    op.create_table(
        "ip_traffic",
        *entity(),
        sa.Column(
            "address_id", sa.String(36), sa.ForeignKey("ip_addresses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("sampled_at", DATETIME(fsp=6), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("in_bps", sa.Float()),
        sa.Column("out_bps", sa.Float()),
        sa.UniqueConstraint("address_id", "source_key", "sampled_at"),
    )
    op.create_index("ix_ip_traffic_address_id", "ip_traffic", ["address_id"])


def downgrade():
    db = op.get_bind()
    for table in ("integrations", "dns_servers", "ip_observations", "ip_traffic"):
        if db.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("IPAM integration data exists; downgrade would discard it")
    if db.scalar(
        sa.text(
            "SELECT COUNT(*) FROM ip_addresses WHERE operating_system != '' OR cabinet != '' OR location != ''"
        )
    ):
        raise RuntimeError("IPAM metadata exists; downgrade would discard it")
    if db.scalar(
        sa.text(
            "SELECT COUNT(*) FROM prefixes WHERE ping_enabled = 1 OR discovery_enabled = 1 OR warning_threshold != 80 OR vlan_device_id IS NOT NULL OR scope_id IS NOT NULL OR ping_interval != 300 OR discovery_interval != 3600"
        )
    ):
        raise RuntimeError("IPAM policies exist; downgrade would discard them")
    op.drop_table("ip_traffic")
    op.drop_table("ip_observations")
    for name in ("operating_system", "cabinet", "location"):
        op.drop_column("ip_addresses", name)
    for name in ("ck_prefix_threshold", "ck_prefix_intervals"):
        op.drop_constraint(name, "prefixes", type_="check")
    for name in ("dns_server_id", "vlan_device_id", "scope_id"):
        op.drop_constraint("fk_prefix_" + name, "prefixes", type_="foreignkey")
        op.drop_index("ix_prefixes_" + name, "prefixes")
    for name in (
        "dns_server_id",
        "vlan_device_id",
        "scope_id",
        "warning_threshold",
        "ping_enabled",
        "ping_interval",
        "discovery_enabled",
        "discovery_interval",
        "last_ping_at",
        "last_discovery_at",
    ):
        op.drop_column("prefixes", name)
    op.drop_table("integrations")
    op.drop_table("dns_servers")
