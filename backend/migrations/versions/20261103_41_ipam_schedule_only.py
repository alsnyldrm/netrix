"""IPAM source collection is schedule-only; enable independent 30-second ICMP checks."""

import sqlalchemy as sa
from alembic import op
from netrix.core import now

revision = "20261103_41"
down_revision = "20261103_40"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_vlan_intervals", "vlans", type_="check")
    op.create_check_constraint(
        "ck_vlan_intervals", "vlans", "ping_interval >= 10 AND discovery_interval >= 60"
    )
    op.alter_column("vlans", "ping_enabled", existing_type=sa.Boolean(), server_default="1")
    op.alter_column("vlans", "ping_interval", existing_type=sa.Integer(), server_default="30")
    op.execute(
        sa.text(
            "UPDATE vlans SET discovery_enabled=0, ping_enabled=1, ping_interval=30 WHERE cidr IS NOT NULL"
        )
    )
    op.execute(sa.text("UPDATE integrations SET interval_seconds=0"))
    conn = op.get_bind()
    jobs = sa.table(
        "jobs",
        sa.column("id", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("status", sa.String()),
        sa.column("result", sa.JSON()),
        sa.column("cancel_requested", sa.Boolean()),
        sa.column("active_key", sa.String()),
        sa.column("finished_at", sa.DateTime()),
        sa.column("error", sa.Text()),
    )
    runs = sa.table("ipam_scan_runs", sa.column("jobs", sa.JSON()))
    rows = list(
        conn.execute(
            sa.select(jobs).where(jobs.c.kind.in_(("ipam_discover", "ipam_ping", "integration")))
        ).mappings()
    )
    roots = {job["job_id"] for (run,) in conn.execute(sa.select(runs.c.jobs)) for job in (run or [])}
    roots.update(row["id"] for row in rows if (row["result"] or {}).get("ipam_origin") == "schedule")
    authorized = set(roots)
    while True:
        children = {
            id
            for row in rows
            if row["id"] in authorized
            for id in (row["result"] or {}).get("source_jobs", [])
        }
        if children <= authorized:
            break
        authorized.update(children)
    for row in rows:
        if row["status"] not in ("queued", "running"):
            continue
        if row["id"] in authorized and row["kind"] != "ipam_ping":
            origin = "schedule" if row["kind"] == "ipam_discover" else "scheduled_source"
            conn.execute(
                jobs.update()
                .where(jobs.c.id == row["id"])
                .values(result={**(row["result"] or {}), "ipam_origin": origin})
            )
        else:
            conn.execute(
                jobs.update()
                .where(jobs.c.id == row["id"])
                .values(
                    status="cancelled",
                    cancel_requested=True,
                    active_key=None,
                    finished_at=now().replace(tzinfo=None),
                    error="Zamanlama dışı IPAM işi yeni çalışma kuralıyla iptal edildi",
                )
            )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM vlans WHERE ping_interval < 30")):
        raise RuntimeError("Set ping intervals to at least 30 seconds before downgrade")
    op.drop_constraint("ck_vlan_intervals", "vlans", type_="check")
    op.create_check_constraint(
        "ck_vlan_intervals", "vlans", "ping_interval >= 30 AND discovery_interval >= 60"
    )
    op.alter_column("vlans", "ping_enabled", existing_type=sa.Boolean(), server_default="0")
    op.alter_column("vlans", "ping_interval", existing_type=sa.Integer(), server_default="300")
    # Do not resurrect cancelled jobs or old independent source schedules.
