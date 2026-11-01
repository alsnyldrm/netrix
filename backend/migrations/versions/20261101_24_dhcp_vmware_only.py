"""Restrict IPAM integrations to DHCP/VMware and remove separate scan approval."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_24"
down_revision = "20261101_23"
branch_labels = None
depends_on = None


def upgrade():
    # Stop retired sources before deleting their records. Preserve job audit history,
    # IP allocations, device inventory and encrypted DHCP/VMware credentials.
    op.execute(
        "UPDATE jobs SET status='cancelled', active_key=NULL, cancel_requested=1, "
        "finished_at=UTC_TIMESTAMP(6) WHERE kind='integration' "
        "AND target_id IN (SELECT id FROM integrations WHERE kind NOT IN ('vcenter','windows_dhcp')) "
        "AND status IN ('queued','running')"
    )
    op.execute("DELETE FROM ip_observations WHERE source IN ('corner_switch','backbone_switch','firewall')")
    op.execute("DELETE FROM integrations WHERE kind NOT IN ('vcenter','windows_dhcp')")
    op.execute(
        "ALTER TABLE integrations DROP CONSTRAINT ck_integration_kind, "
        "ADD CONSTRAINT ck_integration_kind CHECK (kind in ('vcenter','windows_dhcp'))"
    )
    op.drop_constraint("fk_integration_credential", "integrations", type_="foreignkey")
    op.drop_index("ix_integrations_credential_id", table_name="integrations")
    op.drop_column("integrations", "credential_id")
    op.drop_column("integrations", "evidence")
    op.drop_column("vlans", "scan_authorized")


def downgrade():
    # Removed integration records/evidence cannot be reconstructed by a downgrade.
    op.add_column("vlans", sa.Column("scan_authorized", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("integrations", sa.Column("credential_id", sa.String(36), nullable=True))
    op.add_column("integrations", sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))
    op.create_index("ix_integrations_credential_id", "integrations", ["credential_id"])
    op.create_foreign_key(
        "fk_integration_credential", "integrations", "credentials", ["credential_id"], ["id"]
    )
    op.execute(
        "ALTER TABLE integrations DROP CONSTRAINT ck_integration_kind, "
        "ADD CONSTRAINT ck_integration_kind CHECK "
        "(kind in ('vcenter','windows_dhcp','corner_switch','backbone_switch','firewall'))"
    )
