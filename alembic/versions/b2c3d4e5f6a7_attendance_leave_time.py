"""attendance.leave_time (조퇴), 미정(maybe) 투표 제거

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-17 22:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("attendances") as batch:
        batch.add_column(sa.Column("leave_time", sa.String(length=5), nullable=True))
    # 투표 선택지에서 '미정'이 빠졌으므로 기존 미정 투표는 '투표 안 함'으로 되돌린다
    op.execute("UPDATE attendances SET vote = NULL, voted_at = NULL WHERE vote = 'maybe'")


def downgrade() -> None:
    op.execute("UPDATE attendances SET vote = 'yes' WHERE vote = 'early'")
    with op.batch_alter_table("attendances") as batch:
        batch.drop_column("leave_time")
