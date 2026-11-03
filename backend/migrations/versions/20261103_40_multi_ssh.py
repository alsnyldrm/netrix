"""Named personal SSH connections, group routing and one device per owner's group."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from netrix.core import UTCDateTime, now

revision = "20261103_40"
down_revision = "20261103_39"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    duplicates = bind.scalar(
        sa.text("""
        SELECT COUNT(*) FROM (
          SELECT ag.owner_id, agd.device_id FROM access_group_devices agd
          JOIN access_groups ag ON ag.id=agd.group_id
          GROUP BY ag.owner_id,agd.device_id HAVING COUNT(*)>1
        ) conflicts
    """)
    )
    if duplicates:
        raise RuntimeError("Resolve duplicate device memberships within each owner's groups before migration")
    op.create_table(
        "user_ssh_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("encrypted_ssh", sa.Text(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_user_ssh_profile_name"),
        sa.UniqueConstraint("id", "owner_id", name="uq_user_ssh_profile_owner"),
    )
    op.add_column("access_groups", sa.Column("ssh_profile_id", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_access_group_identity_owner", "access_groups", ["id", "owner_id"])
    op.create_index("ix_access_group_ssh_profile_owner", "access_groups", ["ssh_profile_id", "owner_id"])
    op.create_foreign_key(
        "fk_access_group_ssh_owner",
        "access_groups",
        "user_ssh_profiles",
        ["ssh_profile_id", "owner_id"],
        ["id", "owner_id"],
    )
    op.add_column("access_group_devices", sa.Column("owner_id", sa.String(36), nullable=True))
    op.execute(
        sa.text(
            "UPDATE access_group_devices SET owner_id=(SELECT owner_id FROM access_groups WHERE id=access_group_devices.group_id)"
        )
    )
    op.alter_column("access_group_devices", "owner_id", existing_type=sa.String(36), nullable=False)
    for fk in sa.inspect(bind).get_foreign_keys("access_group_devices"):
        if fk["constrained_columns"] == ["group_id"]:
            op.drop_constraint(fk["name"], "access_group_devices", type_="foreignkey")
    op.create_index("ix_access_group_device_owner", "access_group_devices", ["group_id", "owner_id"])
    op.create_foreign_key(
        "fk_access_group_device_owner",
        "access_group_devices",
        "access_groups",
        ["group_id", "owner_id"],
        ["id", "owner_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_access_group_user_device", "access_group_devices", ["owner_id", "device_id"]
    )
    # Ciphertext is copied byte-for-byte; migration never decrypts or prints it.
    for user_id, ciphertext in bind.execute(
        sa.text("SELECT user_id,encrypted_ssh FROM user_workspaces WHERE encrypted_ssh IS NOT NULL")
    ):
        id = str(uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO user_ssh_profiles(id,created_at,updated_at,owner_id,name,encrypted_ssh) VALUES (:id,:created,:updated,:owner,:name,:secret)"
            ),
            {
                "id": id,
                "created": now(),
                "updated": now(),
                "owner": user_id,
                "name": "Kişisel SSH bağlantısı",
                "secret": ciphertext,
            },
        )
        bind.execute(
            sa.text("UPDATE access_groups SET ssh_profile_id=:id WHERE owner_id=:owner"),
            {"id": id, "owner": user_id},
        )
    op.drop_column("user_workspaces", "encrypted_ssh")


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT COUNT(*) FROM user_ssh_profiles")):
        raise RuntimeError(
            "Remove SSH profiles explicitly before downgrade; multiple connections cannot fit the old single profile"
        )
    op.add_column("user_workspaces", sa.Column("encrypted_ssh", sa.Text(), nullable=True))
    op.drop_constraint("uq_access_group_user_device", "access_group_devices", type_="unique")
    op.drop_constraint("fk_access_group_device_owner", "access_group_devices", type_="foreignkey")
    op.create_foreign_key(
        "fk_access_group_devices_group",
        "access_group_devices",
        "access_groups",
        ["group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_access_group_device_owner", "access_group_devices")
    op.drop_column("access_group_devices", "owner_id")
    op.drop_constraint("fk_access_group_ssh_owner", "access_groups", type_="foreignkey")
    op.drop_constraint("uq_access_group_identity_owner", "access_groups", type_="unique")
    op.drop_index("ix_access_group_ssh_profile_owner", "access_groups")
    op.drop_column("access_groups", "ssh_profile_id")
    op.drop_table("user_ssh_profiles")
