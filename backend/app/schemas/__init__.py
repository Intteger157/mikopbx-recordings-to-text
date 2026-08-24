from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TranscriptionStatus, UserRole


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserBase(BaseModel):
    username: str
    email: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    allowed_extensions: list[str] = Field(default_factory=list)


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserUpdate(BaseModel):
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)
    allowed_extensions: list[str] | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    allowed_extensions: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(TokenResponse):
    user: UserResponse


class PBXConfigUpdate(BaseModel):
    api_url: str
    api_key: str | None = None


class PBXConfigResponse(BaseModel):
    api_url: str | None
    has_api_key: bool
    is_connected: bool
    last_sync_at: datetime | None


class PBXSyncRequest(BaseModel):
    date_from: datetime
    date_to: datetime


class PBXSyncResponse(BaseModel):
    state: str = "started"
    message: str


class PBXSyncStatusResponse(BaseModel):
    state: str
    phase: str | None = None
    extensions_synced: int = 0
    calls_synced: int = 0
    calls_skipped: int = 0
    cdr_page: int = 0
    message: str
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ExtensionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    extension: str
    display_name: str | None
    employee_id: str | None


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    call_record_id: int
    status: TranscriptionStatus
    language: str | None
    text: str | None
    segments_json: list[TranscriptionSegment] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class CallRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uniqueid: str
    linkedid: str | None
    call_date: datetime
    src_num: str | None
    dst_num: str | None
    duration: int
    billsec: int
    audio_url: str | None
    miko_user_name: str | None
    disposition: str | None
    has_audio: bool = False
    employee_name: str | None = None
    transcription_status: TranscriptionStatus | None = None


class CallRecordDetail(CallRecordResponse):
    transcription: TranscriptionResponse | None = None


class PaginatedCallsResponse(BaseModel):
    items: list[CallRecordResponse]
    total: int
    page: int
    page_size: int


class TranscriptionEnqueueResponse(BaseModel):
    transcription_id: int
    status: TranscriptionStatus
