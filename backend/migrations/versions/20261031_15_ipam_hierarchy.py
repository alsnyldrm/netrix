"""Institution hierarchy, cabinet elevation and explicit prefix authorization."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261031_15"
down_revision = "20261031_14"
branch_labels = None
depends_on = None


def entity():
    stamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", stamp, nullable=False),
        sa.Column("updated_at", stamp, nullable=False),
    ]


def reference(table, column, target):
    with op.batch_alter_table(table) as b:
        b.add_column(sa.Column(column, sa.String(36), nullable=True))
        b.create_foreign_key(f"fk_{table}_{column}", target, [column], ["id"])
        b.create_index(f"ix_{table}_{column}", [column])


def upgrade():
    op.create_table(
        "model_images",
        *entity(),
        sa.Column("vendor", sa.String(80), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.UniqueConstraint("vendor", "model"),
    )
    op.create_table(
        "institutions",
        *entity(),
        sa.Column("name", sa.String(190), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("code"),
    )
    reference("sites", "institution_id", "institutions")
    reference("sites", "parent_id", "sites")
    reference("prefixes", "institution_id", "institutions")
    reference("cabinets", "sub_site_id", "sites")
    reference("ip_addresses", "device_id", "devices")
    with op.batch_alter_table("cabinets") as b:
        b.add_column(sa.Column("units", sa.Integer(), nullable=False, server_default="42"))
        b.add_column(sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"))
        b.create_check_constraint("ck_cabinet_units", "units >= 1 AND units <= 60")
    op.add_column("prefixes", sa.Column("scan_authorized", sa.Boolean(), nullable=False, server_default="0"))
    # Preserve only existing enabled, covering authorization (never authorize blank installs).
    db = op.get_bind()
    import ipaddress

    for p in db.execute(
        sa.text(
            "SELECT p.id, p.cidr, p.vrf_id, s.cidr AS scope_cidr, s.vrf_id AS scope_vrf, s.enabled FROM prefixes p JOIN discovery_scopes s ON p.scope_id=s.id"
        )
    ).mappings():
        a, b = ipaddress.ip_network(p["cidr"]), ipaddress.ip_network(p["scope_cidr"])
        if p["enabled"] and p["vrf_id"] == p["scope_vrf"] and a.version == b.version and a.subnet_of(b):
            db.execute(sa.text("UPDATE prefixes SET scan_authorized=1 WHERE id=:id"), {"id": p["id"]})
    op.create_table(
        "rack_placements",
        *entity(),
        sa.Column("cabinet_id", sa.String(36), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("start_unit", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.UniqueConstraint("device_id"),
        sa.CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60", name="ck_rack_position"
        ),
    )
    op.create_index("ix_rack_placements_cabinet_id", "rack_placements", ["cabinet_id"])


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT COUNT(*) FROM model_images")):
        raise RuntimeError("Manufacturer image mappings exist; export them before downgrade")
    if (
        db.scalar(sa.text("SELECT COUNT(*) FROM institutions"))
        or db.scalar(sa.text("SELECT COUNT(*) FROM rack_placements"))
        or db.scalar(sa.text("SELECT COUNT(*) FROM cabinets WHERE units != 42"))
        or db.scalar(sa.text("SELECT COUNT(*) FROM ip_addresses WHERE device_id IS NOT NULL"))
    ):
        raise RuntimeError("Hierarchy or rack data exists; export it before downgrade")
    if db.scalar(sa.text("SELECT COUNT(*) FROM prefixes WHERE scan_authorized=1 AND scope_id IS NULL")):
        raise RuntimeError("Standalone prefix authorizations cannot be downgraded")
    op.drop_table("rack_placements")
    op.drop_column("prefixes", "scan_authorized")
    with op.batch_alter_table("cabinets") as b:
        b.drop_constraint("ck_cabinet_units", type_="check")
        b.drop_column("units")
        b.drop_column("lock_version")
    for table, column in [
        ("ip_addresses", "device_id"),
        ("cabinets", "sub_site_id"),
        ("prefixes", "institution_id"),
        ("sites", "parent_id"),
        ("sites", "institution_id"),
    ]:
        with op.batch_alter_table(table) as b:
            b.drop_constraint(f"fk_{table}_{column}", type_="foreignkey")
            b.drop_index(f"ix_{table}_{column}")
            b.drop_column(column)
    op.drop_table("institutions")
    op.drop_table("model_images")
