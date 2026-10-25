"""session_comments.parent_id / is_deleted (대댓글)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-25 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("session_comments") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_session_comments_parent", "session_comments", ["parent_id"], ["id"])
        batch.create_index("ix_session_comments_parent_id", ["parent_id"])


def downgrade() -> None:
    with op.batch_alter_table("session_comments") as batch:
        batch.drop_index("ix_session_comments_parent_id")
        batch.drop_constraint("fk_session_comments_parent", type_="foreignkey")
        batch.drop_column("is_deleted")
        batch.drop_column("parent_id")
