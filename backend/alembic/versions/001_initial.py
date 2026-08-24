"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role = sa.Enum("SUPERADMIN", "MANAGER", "USER", name="user_role", create_type=False)
    transcription_status = sa.Enum(
        "PENDING", "PROCESSING", "COMPLETED", "FAILED", name="transcription_status", create_type=False
    )
    user_role.create(op.get_bind(), checkfirst=True)
    transcription_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "mikopbx_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_url", sa.String(length=512), nullable=True),
        sa.Column("api_key", sa.String(length=512), nullable=True),
        sa.Column("is_connected", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "mikopbx_extensions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("employee_id", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mikopbx_extensions_extension"), "mikopbx_extensions", ["extension"], unique=True)

    op.create_table(
        "user_extensions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "extension", name="uq_user_extension"),
    )
    op.create_index(op.f("ix_user_extensions_extension"), "user_extensions", ["extension"], unique=False)
    op.create_index(op.f("ix_user_extensions_user_id"), "user_extensions", ["user_id"], unique=False)

    op.create_table(
        "call_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uniqueid", sa.String(length=128), nullable=False),
        sa.Column("linkedid", sa.String(length=128), nullable=True),
        sa.Column("call_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("src_num", sa.String(length=64), nullable=True),
        sa.Column("dst_num", sa.String(length=64), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("billsec", sa.Integer(), nullable=False),
        sa.Column("audio_url", sa.String(length=1024), nullable=True),
        sa.Column("recordingfile", sa.String(length=1024), nullable=True),
        sa.Column("miko_user_name", sa.String(length=255), nullable=True),
        sa.Column("disposition", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_call_records_call_date"), "call_records", ["call_date"], unique=False)
    op.create_index(op.f("ix_call_records_dst_num"), "call_records", ["dst_num"], unique=False)
    op.create_index(op.f("ix_call_records_linkedid"), "call_records", ["linkedid"], unique=False)
    op.create_index(op.f("ix_call_records_src_num"), "call_records", ["src_num"], unique=False)
    op.create_index(op.f("ix_call_records_uniqueid"), "call_records", ["uniqueid"], unique=True)

    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_record_id", sa.Integer(), nullable=False),
        sa.Column("status", transcription_status, nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("segments_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["call_record_id"], ["call_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transcriptions_call_record_id"), "transcriptions", ["call_record_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_transcriptions_call_record_id"), table_name="transcriptions")
    op.drop_table("transcriptions")
    op.drop_index(op.f("ix_call_records_uniqueid"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_src_num"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_linkedid"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_dst_num"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_call_date"), table_name="call_records")
    op.drop_table("call_records")
    op.drop_index(op.f("ix_user_extensions_user_id"), table_name="user_extensions")
    op.drop_index(op.f("ix_user_extensions_extension"), table_name="user_extensions")
    op.drop_table("user_extensions")
    op.drop_index(op.f("ix_mikopbx_extensions_extension"), table_name="mikopbx_extensions")
    op.drop_table("mikopbx_extensions")
    op.drop_table("mikopbx_config")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    sa.Enum(name="transcription_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
