"""arcade_runs.detail (슛 기록·점수 흐름) + arcade_challenges (도전장)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-26 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("arcade_runs") as batch:
        batch.add_column(sa.Column("detail", sa.JSON(), nullable=True))
    op.create_table(
        "arcade_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("to_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("beaten_at", sa.DateTime(), nullable=True),
        sa.Column("beaten_score", sa.Integer(), nullable=True),
    )
    op.create_index("ix_arcade_challenges_from_id", "arcade_challenges", ["from_id"])
    op.create_index("ix_arcade_challenges_to_id", "arcade_challenges", ["to_id"])


def downgrade() -> None:
    op.drop_index("ix_arcade_challenges_to_id", "arcade_challenges")
    op.drop_index("ix_arcade_challenges_from_id", "arcade_challenges")
    op.drop_table("arcade_challenges")
    with op.batch_alter_table("arcade_runs") as batch:
        batch.drop_column("detail")
