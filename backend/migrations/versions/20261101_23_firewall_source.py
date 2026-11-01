"""Allow independently configured firewall sources in VLAN IPAM."""

from alembic import op

revision = "20261101_23"
down_revision = "20261101_22"
branch_labels = None
depends_on = None


def upgrade():
    # MariaDB supports dropping and adding CHECK constraints in one atomic ALTER.
    op.execute(
        "ALTER TABLE integrations DROP CONSTRAINT ck_integration_kind, "
        "ADD CONSTRAINT ck_integration_kind CHECK "
        "(kind in ('vcenter','windows_dhcp','corner_switch','backbone_switch','firewall'))"
    )


def downgrade():
    # Existing firewall records make this fail safely rather than deleting sources.
    op.execute(
        "ALTER TABLE integrations DROP CONSTRAINT ck_integration_kind, "
        "ADD CONSTRAINT ck_integration_kind CHECK "
        "(kind in ('vcenter','windows_dhcp','corner_switch','backbone_switch'))"
    )
