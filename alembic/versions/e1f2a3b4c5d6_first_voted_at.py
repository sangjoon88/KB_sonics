"""attendances.first_voted_at (얼리버드)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-25 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.add_column(sa.Column("first_voted_at", sa.DateTime(), nullable=True))
    # 기존 기록: 본인이 투표한 것(대리 투표 아님)은 남아 있는 투표 시각으로 채운다
    op.execute("UPDATE attendances SET first_voted_at = voted_at "
               "WHERE vote IS NOT NULL AND voted_at IS NOT NULL AND proxy_by IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.drop_column("first_voted_at")
