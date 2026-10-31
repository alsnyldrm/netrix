"""Permanently remove traffic collection and its stored data, without backups."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_20"
down_revision = "20261031_19"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    # Processes are stopped before this startup migration runs.
    db.execute(
        sa.text(
            "UPDATE jobs SET status='cancelled', active_key=NULL, cancel_requested=1, "
            "finished_at=CURRENT_TIMESTAMP WHERE kind IN ('monitor','ipam_live') "
            "AND status IN ('queued','running')"
        )
    )
    for table in ("interface_samples", "ip_traffic"):
        if sa.inspect(db).has_table(table):
            op.drop_table(table)
    # Preserve provenance of shared inventory observations without retaining runnable jobs.
    db.execute(
        sa.text(
            "UPDATE jobs SET kind='inventory_import', active_key=NULL, result='{}', error='' "
            "WHERE kind='monitor' AND id IN (SELECT job_id FROM discovery_observations)"
        )
    )
    db.execute(sa.text("DELETE FROM jobs WHERE kind IN ('monitor','ipam_live')"))
    db.execute(
        sa.text(
            "DELETE FROM change_events WHERE kind='port_change' OR "
            "(kind IN ('alert_firing','alert_resolved') AND "
            "JSON_UNQUOTE(JSON_EXTRACT(details,'$.alert_id')) IN "
            "(SELECT id FROM alert_instances WHERE rule_id IN "
            "(SELECT id FROM alert_rules WHERE metric <> 'config_change')))"
        )
    )
    db.execute(
        sa.text(
            "DELETE FROM alert_instances WHERE rule_id IN "
            "(SELECT id FROM alert_rules WHERE metric <> 'config_change')"
        )
    )
    db.execute(sa.text("DELETE FROM alert_rules WHERE metric <> 'config_change'"))
    for table, constraint in (("devices", "ck_device_interval"), ("alert_rules", "ck_alert_metric")):
        checks = {c["name"] for c in sa.inspect(db).get_check_constraints(table)}
        if constraint in checks:
            op.drop_constraint(constraint, table, type_="check")
    for table, columns in (
        ("devices", ("monitoring_enabled", "monitor_interval", "last_monitor_at")),
        ("interfaces", ("monitoring_enabled",)),
    ):
        existing = {c["name"] for c in sa.inspect(db).get_columns(table)}
        for column in columns:
            if column in existing:
                op.drop_column(table, column)
    op.create_check_constraint("ck_device_interval", "devices", "backup_interval >= 0")
    op.create_check_constraint("ck_alert_metric", "alert_rules", "metric = 'config_change'")


def downgrade():
    raise RuntimeError("Traffic removal is permanent; deleted measurements cannot be restored")
