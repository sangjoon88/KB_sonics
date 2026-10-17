"""게스트: members.is_guest, attendances.guest_of

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-17 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.add_column(sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("attendances") as batch:
        batch.add_column(sa.Column("guest_of", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_attendances_guest_of_members", "members", ["guest_of"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.drop_constraint("fk_attendances_guest_of_members", type_="foreignkey")
        batch.drop_column("guest_of")
    with op.batch_alter_table("members") as batch:
        batch.drop_column("is_guest")
