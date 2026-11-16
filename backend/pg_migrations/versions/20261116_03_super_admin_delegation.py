"""Allow super-admin delegation to both local and Entra users."""

from alembic import op

revision = "20261116_03"
down_revision = "20261116_02"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_saml_no_super_admin", "users", type_="check", schema="yonetim")
    op.drop_constraint("ck_user_super_admin_email", "users", type_="check", schema="yonetim")


def downgrade():
    # Refuse downgrade if delegated roles exist; do not silently change access.
    op.create_check_constraint(
        "ck_user_super_admin_email",
        "users",
        "role <> 'super_admin' OR lower(email) = 'alisan.yildirim@fbu.edu.tr'",
        schema="yonetim",
    )
    op.create_check_constraint(
        "ck_saml_no_super_admin", "users", "auth_source = 'local' OR role <> 'super_admin'", schema="yonetim"
    )
