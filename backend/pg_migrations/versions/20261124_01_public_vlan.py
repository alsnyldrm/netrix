"""Public VLANs use ping-only discovery."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_01"
down_revision = "20261122_06"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "vlans",
        sa.Column("network_type", sa.String(10), nullable=False, server_default="local"),
        schema="ip_adres_yonetimi",
    )
    op.create_check_constraint(
        "ck_vlan_network_type", "vlans", "network_type IN ('local', 'public')", schema="ip_adres_yonetimi"
    )


def downgrade():
    op.drop_constraint("ck_vlan_network_type", "vlans", schema="ip_adres_yonetimi", type_="check")
    op.drop_column("vlans", "network_type", schema="ip_adres_yonetimi")
