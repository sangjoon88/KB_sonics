"""member.is_owner (관리자 / 운영진 구분)

Revision ID: a1b2c3d4e5f6
Revises: cfa6a9d6022e
Create Date: 2026-10-17 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "cfa6a9d6022e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.add_column(sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()))
    # 기존 DB: 가장 먼저 만들어진 운영진을 관리자로 지정
    op.execute("""
        UPDATE members SET is_owner = TRUE
        WHERE id = (SELECT MIN(id) FROM members WHERE is_admin = TRUE)
    """)


def downgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_column("is_owner")
