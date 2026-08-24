from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import TranscriptionStatus, UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    allowed_extensions: Mapped[list["UserExtension"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserExtension(Base):
    __tablename__ = "user_extensions"
    __table_args__ = (UniqueConstraint("user_id", "extension", name="uq_user_extension"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    extension: Mapped[str] = mapped_column(String(32), index=True)

    user: Mapped["User"] = relationship(back_populates="allowed_extensions")


class MikoPBXConfig(Base):
    __tablename__ = "mikopbx_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MikoPBXExtension(Base):
    __tablename__ = "mikopbx_extensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extension: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uniqueid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    linkedid: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    call_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_num: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    dst_num: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    billsec: Mapped[int] = mapped_column(Integer, default=0)
    audio_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    recordingfile: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    miko_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(64), nullable=True)

    transcription: Mapped["Transcription | None"] = relationship(
        back_populates="call_record", uselist=False, cascade="all, delete-orphan"
    )


class Transcription(Base):
    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_record_id: Mapped[int] = mapped_column(
        ForeignKey("call_records.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[TranscriptionStatus] = mapped_column(
        Enum(TranscriptionStatus, name="transcription_status"), default=TranscriptionStatus.PENDING
    )
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    call_record: Mapped["CallRecord"] = relationship(back_populates="transcription")
