"""Full access belongs only to the designated owner; SSH remains an explicit grant."""

from alembic import op

revision = "20261103_43"
down_revision = "20261103_42"
branch_labels = None
depends_on = None


def upgrade():
    # Atomic constraint replacement on MariaDB; existing explicit SSH grants stay intact.
    op.execute("""
        ALTER TABLE users DROP CONSTRAINT ck_user_role,
        ADD CONSTRAINT ck_user_role CHECK (role in ('super_admin','admin','operator','viewer')),
        ADD CONSTRAINT ck_user_super_admin_email
            CHECK (role <> 'super_admin' OR lower(email) = 'alisan.yildirim@fbu.edu.tr')
    """)
    op.execute("""
        UPDATE users SET role = 'super_admin'
        WHERE lower(email) = 'alisan.yildirim@fbu.edu.tr'
    """)


def downgrade():
    op.execute("UPDATE users SET role = 'admin', ssh_access = 1 WHERE role = 'super_admin'")
    op.execute("""
        ALTER TABLE users DROP CONSTRAINT ck_user_super_admin_email,
        DROP CONSTRAINT ck_user_role,
        ADD CONSTRAINT ck_user_role CHECK (role in ('admin','operator','viewer'))
    """)
