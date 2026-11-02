"""Reciprocal rear patch ports and durable targets that may not exist yet."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_31"
down_revision = "20261101_30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("patch_ports", sa.Column("peer_port_id", sa.String(36), nullable=True))
    op.add_column("patch_ports", sa.Column("external_data", sa.JSON(), nullable=False, server_default="{}"))
    op.create_unique_constraint("uq_patch_peer_port", "patch_ports", ["peer_port_id"])
    op.create_foreign_key(
        "fk_patch_peer_port", "patch_ports", "patch_ports", ["peer_port_id"], ["id"], ondelete="SET NULL"
    )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT count(*) FROM patch_ports WHERE peer_port_id IS NOT NULL OR JSON_LENGTH(external_data) > 0"
        )
    ):
        raise RuntimeError("External patch connections exist; export or clear them before downgrade")
    op.drop_constraint("fk_patch_peer_port", "patch_ports", type_="foreignkey")
    op.drop_constraint("uq_patch_peer_port", "patch_ports", type_="unique")
    op.drop_column("patch_ports", "external_data")
    op.drop_column("patch_ports", "peer_port_id")
