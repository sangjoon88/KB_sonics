"""모든 멤버 PIN (admin_pin_hash → pin_hash), 부 포지션, 몸무게

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-18 01:00:00

"""
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PIN = "1234"


def upgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.alter_column("admin_pin_hash", new_column_name="pin_hash", existing_type=sa.String(100))
        batch.add_column(sa.Column("position2", sa.String(length=1), nullable=True))
        batch.add_column(sa.Column("weight_kg", sa.Integer(), nullable=True))
    # PIN이 없던 일반 멤버: 초기 PIN 부여 + 첫 로그인 때 변경
    hashed = bcrypt.hashpw(DEFAULT_PIN.encode(), bcrypt.gensalt()).decode()
    op.get_bind().execute(
        sa.text("UPDATE members SET pin_hash = :h, pin_must_change = :t "
                "WHERE pin_hash IS NULL AND is_guest = :f"),
        {"h": hashed, "t": True, "f": False})


def downgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_column("weight_kg")
        batch.drop_column("position2")
        batch.alter_column("pin_hash", new_column_name="admin_pin_hash", existing_type=sa.String(100))
