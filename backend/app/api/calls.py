import mimetypes
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.database import get_db
from app.models import CallRecord, Transcription, User
from app.models.enums import TranscriptionStatus
from app.schemas import (
    CallRecordDetail,
    CallRecordResponse,
    PaginatedCallsResponse,
    TranscriptionEnqueueResponse,
    TranscriptionResponse,
    TranscriptionSegment,
)
from app.services.call_service import apply_call_rbac_filter, get_call_for_user
from app.services.sync_service import get_pbx_client
from app.tasks.transcription import transcribe_call

router = APIRouter(prefix="/api/calls", tags=["calls"])


def _call_to_response(call: CallRecord) -> CallRecordResponse:
    transcription_status = call.transcription.status if call.transcription else None
    return CallRecordResponse(
        id=call.id,
        uniqueid=call.uniqueid,
        linkedid=call.linkedid,
        call_date=call.call_date,
        src_num=call.src_num,
        dst_num=call.dst_num,
        duration=call.duration,
        billsec=call.billsec,
        audio_url=call.audio_url,
        miko_user_name=call.miko_user_name,
        disposition=call.disposition,
        has_audio=bool(call.audio_url),
        transcription_status=transcription_status,
    )


def _transcription_to_response(transcription: Transcription | None) -> TranscriptionResponse | None:
    if not transcription:
        return None
    segments = None
    if transcription.segments_json:
        segments = [TranscriptionSegment(**segment) for segment in transcription.segments_json]
    return TranscriptionResponse(
        id=transcription.id,
        call_record_id=transcription.call_record_id,
        status=transcription.status,
        language=transcription.language,
        text=transcription.text,
        segments_json=segments,
        error_message=transcription.error_message,
        created_at=transcription.created_at,
        completed_at=transcription.completed_at,
    )


@router.get("", response_model=PaginatedCallsResponse)
async def list_calls(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    src_num: str | None = None,
    dst_num: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(CallRecord).options(selectinload(CallRecord.transcription))
    stmt = apply_call_rbac_filter(stmt, current_user)

    if date_from:
        stmt = stmt.where(CallRecord.call_date >= date_from)
    if date_to:
        stmt = stmt.where(CallRecord.call_date <= date_to)
    if src_num:
        stmt = stmt.where(CallRecord.src_num == src_num)
    if dst_num:
        stmt = stmt.where(CallRecord.dst_num == dst_num)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                CallRecord.src_num.ilike(pattern),
                CallRecord.dst_num.ilike(pattern),
                CallRecord.miko_user_name.ilike(pattern),
                CallRecord.uniqueid.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(CallRecord.call_date.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    calls = result.scalars().all()

    return PaginatedCallsResponse(
        items=[_call_to_response(call) for call in calls],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{call_id}", response_model=CallRecordDetail)
async def get_call(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    response = _call_to_response(call)
    return CallRecordDetail(**response.model_dump(), transcription=_transcription_to_response(call.transcription))


@router.get("/{call_id}/audio")
async def stream_call_audio(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call or not call.audio_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")

    client = await get_pbx_client(db)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MikoPBX is not configured")

    httpx_client, response = await client.stream_audio(call.audio_url)
    media_type = response.headers.get("content-type") or mimetypes.guess_type(call.recordingfile or "")[0] or "audio/webm"

    async def iterator():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await httpx_client.aclose()

    return StreamingResponse(iterator(), media_type=media_type)


@router.post("/{call_id}/transcribe", response_model=TranscriptionEnqueueResponse)
async def enqueue_transcription(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if not call.audio_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call has no recording")

    if call.transcription and call.transcription.status in {
        TranscriptionStatus.PENDING,
        TranscriptionStatus.PROCESSING,
        TranscriptionStatus.COMPLETED,
    }:
        return TranscriptionEnqueueResponse(
            transcription_id=call.transcription.id,
            status=call.transcription.status,
        )

    if call.transcription and call.transcription.status == TranscriptionStatus.FAILED:
        transcription = call.transcription
        transcription.status = TranscriptionStatus.PENDING
        transcription.error_message = None
    else:
        transcription = Transcription(call_record_id=call.id, status=TranscriptionStatus.PENDING)
        db.add(transcription)

    await db.commit()
    await db.refresh(transcription)
    transcribe_call.delay(transcription.id)
    return TranscriptionEnqueueResponse(transcription_id=transcription.id, status=transcription.status)


@router.get("/{call_id}/transcription", response_model=TranscriptionResponse)
async def get_transcription(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if not call.transcription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcription not found")
    return _transcription_to_response(call.transcription)
