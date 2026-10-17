"""sessions.start_time, 투표 마감 기본 없음

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-18 02:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("start_time", sa.String(length=5), nullable=True))
    op.execute("UPDATE sessions SET start_time = '08:00' WHERE start_time IS NULL")
    # 투표 마감을 두지 않기로 함: 아직 투표 중인 경기의 마감 시각 제거
    op.execute("UPDATE sessions SET vote_deadline = NULL WHERE status = 'open'")


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("start_time")
