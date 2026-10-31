"""Persist the institution, location and sublocation selected for each IP."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_17"
down_revision = "20261031_16"
branch_labels = None
depends_on = None

RELATIONS = {"institution_id": "institutions", "site_id": "sites", "sub_site_id": "sites"}


def upgrade():
    with op.batch_alter_table("ip_addresses") as batch:
        for column, target in RELATIONS.items():
            batch.add_column(sa.Column(column, sa.String(36), nullable=True))
            batch.create_foreign_key(f"fk_ip_addresses_{column}", target, [column], ["id"])
            batch.create_index(f"ix_ip_addresses_{column}", [column])
    db = op.get_bind()
    sites = {r.id: r for r in db.execute(sa.text("SELECT id,name,parent_id,institution_id FROM sites"))}
    by_name = {}
    for site in sites.values():
        by_name.setdefault(site.name, []).append(site)
    # Only unambiguous existing manual values can establish a relationship.
    # Unmatched/duplicate names and institution-less legacy sites retain their text.
    rows = db.execute(sa.text("SELECT id,location FROM ip_addresses WHERE location <> ''")).all()
    for row in rows:
        matches = by_name.get(row.location, [])
        if len(matches) != 1:
            continue
        leaf = matches[0]
        root = sites.get(leaf.parent_id) if leaf.parent_id else leaf
        if (
            not root
            or root.parent_id
            or not root.institution_id
            or root.institution_id != leaf.institution_id
        ):
            continue
        db.execute(
            sa.text(
                "UPDATE ip_addresses SET institution_id=:institution,site_id=:site,sub_site_id=:sub WHERE id=:id"
            ),
            {
                "id": row.id,
                "institution": root.institution_id,
                "site": root.id,
                "sub": leaf.id if leaf.parent_id else None,
            },
        )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM ip_addresses WHERE institution_id IS NOT NULL OR site_id IS NOT NULL OR sub_site_id IS NOT NULL"
        )
    ):
        raise RuntimeError("IP location assignments exist; export and clear them before downgrade")
    with op.batch_alter_table("ip_addresses") as batch:
        for column in reversed(RELATIONS):
            batch.drop_constraint(f"fk_ip_addresses_{column}", type_="foreignkey")
            batch.drop_index(f"ix_ip_addresses_{column}")
            batch.drop_column(column)
