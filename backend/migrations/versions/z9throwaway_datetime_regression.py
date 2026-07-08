"""THROWAWAY (Phase 2.5e regression-proof only, will be deleted): revert
scans timestamps to naive, reproducing the Phase 1 datetime-tz bug.

Revision ID: z9throwaway01
Revises: 347a304e5105
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'z9throwaway01'
down_revision: Union[str, Sequence[str], None] = '347a304e5105'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('scans', 'started_at', type_=sa.DateTime(timezone=False))
    op.alter_column('scans', 'completed_at', type_=sa.DateTime(timezone=False))


def downgrade() -> None:
    op.alter_column('scans', 'started_at', type_=sa.DateTime(timezone=True))
    op.alter_column('scans', 'completed_at', type_=sa.DateTime(timezone=True))
