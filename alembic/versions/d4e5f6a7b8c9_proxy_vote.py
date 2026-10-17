"""attendances.proxy_by (운영진 대리 투표)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-18 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.add_column(sa.Column("proxy_by", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_attendances_proxy_by_members", "members", ["proxy_by"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.drop_constraint("fk_attendances_proxy_by_members", type_="foreignkey")
        batch.drop_column("proxy_by")
