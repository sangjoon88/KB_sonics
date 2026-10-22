"""arcade_runs (미니게임: 3점슛 콘테스트 기록)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-22 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "arcade_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("game", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("made", sa.Integer(), nullable=True),
    )
    op.create_index("ix_arcade_runs_member_id", "arcade_runs", ["member_id"])
    op.create_index("ix_arcade_runs_finished_at", "arcade_runs", ["finished_at"])


def downgrade() -> None:
    op.drop_index("ix_arcade_runs_finished_at", table_name="arcade_runs")
    op.drop_index("ix_arcade_runs_member_id", table_name="arcade_runs")
    op.drop_table("arcade_runs")
