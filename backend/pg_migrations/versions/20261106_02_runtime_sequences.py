"""Permit native backups and generated IDs without granting runtime DDL."""

from alembic import op

revision = "20261106_02"
down_revision = "20261106_01"
branch_labels = None
depends_on = None


def upgrade():
    import sqlalchemy as sa

    c = op.get_bind()
    op.execute("LOCK TABLE firmware.firmware_events IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        SELECT setval(
            CAST(pg_get_serial_sequence('firmware.firmware_events', 'id') AS regclass),
            GREATEST(COALESCE((SELECT max(id) FROM firmware.firmware_events), 1),
                     (SELECT last_value FROM firmware.firmware_events_id_seq)),
            (SELECT is_called FROM firmware.firmware_events_id_seq)
                OR EXISTS (SELECT 1 FROM firmware.firmware_events)
        )
    """)
    if c.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='netrix_app')")):
        schemas = (
            "genel_bakis",
            "envanter",
            "baglanti",
            "ip_adres_yonetimi",
            "firmware",
            "konfigurasyon",
            "operasyon",
            "yonetim",
        )
        for schema in schemas:
            op.execute("GRANT USAGE ON SCHEMA " + schema + " TO netrix_app")
            op.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA " + schema + " TO netrix_app"
            )
            op.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA "
                + schema
                + " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO netrix_app"
            )
            op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA " + schema + " TO netrix_app")
            op.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA "
                + schema
                + " GRANT USAGE, SELECT ON SEQUENCES TO netrix_app"
            )
        op.execute("REVOKE INSERT, UPDATE, DELETE ON yonetim.alembic_version FROM netrix_app")


def downgrade():
    raise RuntimeError("Removing sequence privileges would break generated IDs and native backups")
