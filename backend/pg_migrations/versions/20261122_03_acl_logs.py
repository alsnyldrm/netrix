"""Device-originated ACL events owned by the blacklist menu."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_03"
down_revision = "20261122_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "acl_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("peer_address", sa.String(45), nullable=False),
        sa.Column("transport", sa.String(12), nullable=False),
        sa.Column("acl", sa.String(64)),
        sa.Column("source_address", sa.String(45)),
        sa.Column("destination_address", sa.String(45)),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["envanter.devices.id"], deferrable=True, initially="IMMEDIATE"),
        sa.CheckConstraint("action in ('deny','permit','unknown')", name="ck_acl_logs_action"),
        sa.CheckConstraint("transport in ('syslog_udp','syslog_tcp')", name="ck_acl_logs_transport"),
        schema="kara_liste",
    )
    op.create_index("ix_acl_logs_received", "acl_logs", ["received_at", "id"], schema="kara_liste")
    op.create_index("ix_acl_logs_device_received", "acl_logs", ["device_id", "received_at"], schema="kara_liste")
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname='netrix_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON kara_liste.acl_logs TO netrix_app;
          END IF;
        END $$;
    """)


def downgrade():
    op.drop_table("acl_logs", schema="kara_liste")
