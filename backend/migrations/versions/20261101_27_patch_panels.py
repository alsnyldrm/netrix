"""Passive cabinet patch panels and manual per-port cabling records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261101_27"
down_revision = "20261101_26"
branch_labels = None
depends_on = None


def stamps():
    stamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", stamp, nullable=False),
        sa.Column("updated_at", stamp, nullable=False),
    ]


def upgrade():
    op.create_table(
        "patch_panels",
        *stamps(),
        sa.Column("cabinet_id", sa.String(36), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("start_unit", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("port_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("cabinet_id", "name", name="uq_patch_panel_name"),
        sa.CheckConstraint("kind in ('cat','fiber')", name="ck_patch_panel_kind"),
        sa.CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60", name="ck_patch_panel_position"
        ),
        sa.CheckConstraint("port_count >= 1 AND port_count <= 288", name="ck_patch_panel_count"),
    )
    op.create_index("ix_patch_panels_cabinet_id", "patch_panels", ["cabinet_id"])
    op.create_table(
        "patch_ports",
        *stamps(),
        sa.Column(
            "panel_id", sa.String(36), sa.ForeignKey("patch_panels.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column(
            "device_id", sa.String(36), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "interface_id", sa.String(36), sa.ForeignKey("interfaces.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("device_name", sa.String(190), nullable=False),
        sa.Column("port_name", sa.String(120), nullable=False),
        sa.Column("cable_model", sa.String(30), nullable=False),
        sa.UniqueConstraint("panel_id", "number", name="uq_patch_port_number"),
        sa.UniqueConstraint("panel_id", "position", name="uq_patch_port_position"),
        sa.CheckConstraint("position >= 1 AND position <= 288", name="ck_patch_port_position"),
        sa.CheckConstraint(
            "cable_model in ('','Cat5','Cat6','Cat7','OM3','OM4','Multimode MM','Singlemode SM')",
            name="ck_patch_cable_model",
        ),
    )
    for key in ("panel_id", "device_id", "interface_id"):
        op.create_index("ix_patch_ports_" + key, "patch_ports", [key])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM patch_panels")):
        raise RuntimeError("Patch panels exist; export them before downgrade")
    op.drop_table("patch_ports")
    op.drop_table("patch_panels")
