"""created_at to double

迁移 ID: 3f8c1d2e4a5b
父迁移: 9a1f4c7b2d30
创建时间: 2026-11-21 12:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8c1d2e4a5b"
down_revision: str | Sequence[str] | None = "9a1f4c7b2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade(name: str = "") -> None:
    if name:
        return
    # MySQL FLOAT 只有 32 位，时间戳等值比较会因精度丢失失败；改 DOUBLE 后精确匹配
    with op.batch_alter_table("amrita_memory_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.Float(),
            type_=sa.Double(),
            existing_nullable=False,
        )


def downgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("amrita_memory_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.Double(),
            type_=sa.Float(),
            existing_nullable=False,
        )
