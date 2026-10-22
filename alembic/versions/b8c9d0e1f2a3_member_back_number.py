"""members.back_number (백넘버) + 유니폼 주문서(2026) 기준 초기값

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-22 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 유니폼_주문서(소닉스)26 — 이름이 DB와 정확히 같은 멤버만 채워지고, 없는 이름은 건너뛴다
INITIAL_NUMBERS = {
    "채상재": "32", "이상준": "6", "이원섭": "11", "설진웅": "18", "구현모": "99", "인재연": "3",
    "김민재": "5", "이명헌": "0", "이상인": "13", "임동민": "8", "최재웅": "21", "피윤수": "15",
    "이동훈": "5", "진영일": "7", "박재완": "37", "정진욱": "55", "방태원": "24", "전윤상": "14",
}


def upgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.add_column(sa.Column("back_number", sa.String(length=2), nullable=True))
    members = sa.table("members", sa.column("name", sa.String), sa.column("back_number", sa.String))
    for name, no in INITIAL_NUMBERS.items():
        op.execute(members.update().where(members.c.name == name).values(back_number=no))


def downgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_column("back_number")
