"""add mikopbx_cdr_id to call_records

Revision ID: 002_call_mikopbx_cdr_id
Revises: 001_initial
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_call_mikopbx_cdr_id"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("call_records", sa.Column("mikopbx_cdr_id", sa.Integer(), nullable=True))
    op.create_index("ix_call_records_mikopbx_cdr_id", "call_records", ["mikopbx_cdr_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_call_records_mikopbx_cdr_id", table_name="call_records")
    op.drop_column("call_records", "mikopbx_cdr_id")
