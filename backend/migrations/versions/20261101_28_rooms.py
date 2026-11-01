"""Room attributes and cabinet numbers scoped to their room."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_28"
down_revision = "20261101_27"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sites", sa.Column("floor_number", sa.String(40), nullable=False, server_default=""))
    op.add_column("sites", sa.Column("department_name", sa.String(120), nullable=False, server_default=""))
    op.create_unique_constraint("uq_cabinet_room_number", "cabinets", ["sub_site_id", "name"])
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("cabinets"):
        if constraint["column_names"] == ["name"]:
            op.drop_constraint(constraint["name"], "cabinets", type_="unique")


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM sites WHERE floor_number <> '' OR department_name <> ''")):
        raise RuntimeError("Room details exist; export them before downgrade")
    if bind.execute(sa.text("SELECT name FROM cabinets GROUP BY name HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Cabinet numbers repeat across rooms; rename them before downgrade")
    op.drop_constraint("uq_cabinet_room_number", "cabinets", type_="unique")
    op.create_unique_constraint("name", "cabinets", ["name"])
    op.drop_column("sites", "department_name")
    op.drop_column("sites", "floor_number")
