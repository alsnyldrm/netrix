"""Track desired blacklist state, verified device ACL content and removals."""

import json

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261122_04"
down_revision = "20261122_03"
branch_labels = None
depends_on = None
SCHEMA = "kara_liste"


def upgrade():
    op.add_column(
        "acl_groups",
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_acl_groups_status", "acl_groups", "status in ('active','deleting')", schema=SCHEMA
    )
    op.add_column(
        "blacklist_entries",
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        schema=SCHEMA,
    )
    op.add_column("blacklist_entries", sa.Column("expires_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column("blacklist_entries", sa.Column("updated_by", sa.String(36)), schema=SCHEMA)
    op.create_foreign_key(
        "fk_blacklist_entries_updated_by",
        "blacklist_entries",
        "users",
        ["updated_by"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema="yonetim",
    )
    op.create_check_constraint(
        "ck_blacklist_entries_status",
        "blacklist_entries",
        "status in ('draft','active','disabled','deleting')",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_kara_liste_blacklist_entries_status", "blacklist_entries", ["status"], schema=SCHEMA
    )

    # Deliveries remain as history after an entry is deleted.
    op.alter_column("blacklist_deliveries", "entry_id", nullable=True, schema=SCHEMA)
    op.drop_constraint(
        "blacklist_deliveries_entry_id_fkey", "blacklist_deliveries", type_="foreignkey", schema=SCHEMA
    )
    op.create_foreign_key(
        "blacklist_deliveries_entry_id_fkey",
        "blacklist_deliveries",
        "blacklist_entries",
        ["entry_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )

    op.create_table(
        "device_acl_states",
        sa.Column("device_id", sa.String(36), primary_key=True),
        sa.Column("profile", JSONB()),
        sa.Column("addresses", JSONB(), nullable=False, server_default="[]"),
        sa.Column("group_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="synced"),
        sa.Column("attempted", JSONB()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["envanter.devices.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status in ('synced','dirty')", name="ck_device_acl_states_status"),
        schema=SCHEMA,
    )

    # The previous engine only added addresses. Every verified delivery is
    # therefore still present on its device, under the profile it was sent with.
    if not context.is_offline_mode():
        seed_states(op.get_bind())
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname='netrix_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON kara_liste.device_acl_states TO netrix_app;
            END IF;
        END $$;
    """)


def seed_states(bind):
    rows = bind.execute(
        sa.text("""
            SELECT d.entry_id, d.device_id, d.payload, j.status, j.finished_at, d.created_at
            FROM kara_liste.blacklist_deliveries d
            JOIN operasyon.jobs j ON j.id = d.job_id
            ORDER BY d.created_at
        """)
    ).fetchall()
    states, delivered = {}, set()
    for entry_id, device_id, payload, status, finished_at, _ in rows:
        payload = payload if isinstance(payload, dict) else json.loads(payload)
        state = states.setdefault(
            device_id,
            {"profile": None, "addresses": set(), "group_ids": set(), "dirty": False, "verified_at": None},
        )
        if state["profile"] not in (None, payload["profile"]):
            # A profile change was never supported; keep the newest profile as uncertain.
            state.update(addresses=set(), group_ids=set(), dirty=True)
        state["profile"] = payload["profile"]
        if status == "succeeded":
            state["addresses"].add(payload["address"])
            state["group_ids"].update(payload.get("group_ids", []))
            state["verified_at"] = finished_at
            delivered.add(entry_id)
        else:
            state["dirty"] = True
            state.setdefault("attempted_addresses", set()).add(payload["address"])
            state["group_ids"].update(payload.get("group_ids", []))
            delivered.add(entry_id)
    for device_id, state in states.items():
        attempted = None
        if state["dirty"]:
            attempted = {
                "profile": state["profile"],
                "addresses": sorted(state["addresses"] | state.get("attempted_addresses", set())),
                "group_ids": sorted(state["group_ids"]),
            }
        bind.execute(
            sa.text("""
                INSERT INTO kara_liste.device_acl_states
                    (device_id, profile, addresses, group_ids, status, attempted, verified_at, updated_at)
                VALUES (:device_id, CAST(:profile AS JSONB), CAST(:addresses AS JSONB),
                        CAST(:group_ids AS JSONB), :status, CAST(:attempted AS JSONB), :verified_at, now())
            """),
            {
                "device_id": device_id,
                "profile": json.dumps(state["profile"]),
                "addresses": json.dumps(sorted(state["addresses"])),
                "group_ids": json.dumps(sorted(state["group_ids"])),
                "status": "dirty" if state["dirty"] else "synced",
                "attempted": json.dumps(attempted) if attempted else None,
                "verified_at": state["verified_at"],
            },
        )
    for entry_id in delivered:
        bind.execute(
            sa.text("UPDATE kara_liste.blacklist_entries SET status = 'active' WHERE id = :id"),
            {"id": entry_id},
        )


def downgrade():
    op.drop_table("device_acl_states", schema=SCHEMA)
    op.execute("DELETE FROM kara_liste.blacklist_deliveries WHERE entry_id IS NULL")
    op.drop_constraint(
        "blacklist_deliveries_entry_id_fkey", "blacklist_deliveries", type_="foreignkey", schema=SCHEMA
    )
    op.create_foreign_key(
        "blacklist_deliveries_entry_id_fkey",
        "blacklist_deliveries",
        "blacklist_entries",
        ["entry_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.alter_column("blacklist_deliveries", "entry_id", nullable=False, schema=SCHEMA)
    op.drop_index("ix_kara_liste_blacklist_entries_status", table_name="blacklist_entries", schema=SCHEMA)
    op.drop_constraint("ck_blacklist_entries_status", "blacklist_entries", type_="check", schema=SCHEMA)
    op.drop_constraint(
        "fk_blacklist_entries_updated_by", "blacklist_entries", type_="foreignkey", schema=SCHEMA
    )
    for column in ("updated_by", "expires_at", "status"):
        op.drop_column("blacklist_entries", column, schema=SCHEMA)
    op.drop_constraint("ck_acl_groups_status", "acl_groups", type_="check", schema=SCHEMA)
    op.drop_column("acl_groups", "status", schema=SCHEMA)
