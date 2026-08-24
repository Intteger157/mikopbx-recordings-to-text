import mimetypes
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.database import get_db
from app.models import CallRecord, MikoPBXExtension, Transcription, User
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
from app.services.recording_service import fetch_call_recording, resolve_call_audio_url
from app.services.sync_service import get_pbx_client
from app.utils.timezone import localize_naive_to_utc
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/api/calls", tags=["calls"])

STALE_TRANSCRIPTION_MINUTES = 15
# First run downloads the Whisper model, so allow a generous window
STALE_PROCESSING_MINUTES = 40
# MikoPBX caps every response at ~20 KB and the whole API at 180 requests per
# minute, so the player only streams short recordings directly; longer ones are
# served from the cache the transcription worker fills.
PLAYER_RANGE_REQUEST_BUDGET = 60


def _mark_stale_transcription(transcription: Transcription | None) -> Transcription | None:
    if not transcription:
        return transcription
    if transcription.status not in {TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING}:
        return transcription

    updated_at = transcription.completed_at or transcription.created_at
    age = datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
    limit_minutes = (
        STALE_PROCESSING_MINUTES
        if transcription.status == TranscriptionStatus.PROCESSING
        else STALE_TRANSCRIPTION_MINUTES
    )
    if age.total_seconds() <= limit_minutes * 60:
        return transcription

    was_processing = transcription.status == TranscriptionStatus.PROCESSING
    transcription.status = TranscriptionStatus.FAILED
    transcription.error_message = (
        "Transcription timed out while downloading or processing audio. "
        "Check celery-worker logs and MikoPBX /cdr/download?token= API."
        if was_processing
        else "Transcription worker did not start. On the server run: "
        "docker compose ps celery-worker && docker compose logs celery-worker --tail 30"
    )
    return transcription


def _resolve_employee_name(call: CallRecord, ext_map: dict[str, str]) -> str | None:
    for number in (call.src_num, call.dst_num):
        if number and number in ext_map:
            return ext_map[number]
    return call.miko_user_name


def _call_to_response(call: CallRecord, ext_map: dict[str, str] | None = None) -> CallRecordResponse:
    transcription_status = call.transcription.status if call.transcription else None
    ext_map = ext_map or {}
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
        has_audio=bool(call.audio_url or call.mikopbx_cdr_id),
        employee_name=_resolve_employee_name(call, ext_map),
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

    if date_from is None and date_to is None:
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=30)
    elif date_from is None and date_to is not None:
        date_from = date_to - timedelta(days=30)
    elif date_to is None and date_from is not None:
        date_to = datetime.now(timezone.utc)

    date_from = localize_naive_to_utc(date_from)
    date_to = localize_naive_to_utc(date_to)

    stmt = stmt.where(CallRecord.call_date >= date_from)
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

    ext_result = await db.execute(select(MikoPBXExtension))
    ext_map = {row.extension: row.display_name for row in ext_result.scalars() if row.display_name}

    return PaginatedCallsResponse(
        items=[_call_to_response(call, ext_map) for call in calls],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/worker-status")
async def get_transcription_worker_status(_: User = Depends(get_current_user)):
    try:
        ping = celery_app.control.inspect(timeout=3.0).ping() or {}
    except Exception:
        ping = {}
    workers = list(ping.keys())
    return {"online": bool(workers), "workers": workers}


@router.get("/{call_id}", response_model=CallRecordDetail)
async def get_call(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    if call.transcription:
        _mark_stale_transcription(call.transcription)
        await db.commit()
        await db.refresh(call)

    ext_result = await db.execute(select(MikoPBXExtension))
    ext_map = {row.extension: row.display_name for row in ext_result.scalars() if row.display_name}
    response = _call_to_response(call, ext_map)
    return CallRecordDetail(**response.model_dump(), transcription=_transcription_to_response(call.transcription))


@router.get("/{call_id}/audio")
async def stream_call_audio(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call or (not call.audio_url and not call.mikopbx_cdr_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")

    client = await get_pbx_client(db)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MikoPBX is not configured")

    try:
        audio_bytes, content_type = await fetch_call_recording(
            db,
            client,
            call,
            read_timeout=25.0,
            max_urls=1,
            max_range_requests=PLAYER_RANGE_REQUEST_BUDGET,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    media_type = content_type or mimetypes.guess_type(call.recordingfile or "")[0] or "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/{call_id}/audio-debug")
async def debug_call_audio(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    client = await get_pbx_client(db)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MikoPBX is not configured")

    stored_url = call.audio_url
    refresh_error: str | None = None
    try:
        audio_url = await resolve_call_audio_url(db, client, call)
    except RuntimeError as exc:
        refresh_error = str(exc)
        audio_url = stored_url

    attempts = await client.probe_recording_urls(
        audio_url or "",
        recordingfile=call.recordingfile,
        cdr_id=call.mikopbx_cdr_id,
    ) if audio_url else []

    return {
        "call_id": call.id,
        "uniqueid": call.uniqueid,
        "mikopbx_cdr_id": call.mikopbx_cdr_id,
        "recordingfile": call.recordingfile,
        "stored_audio_url": stored_url,
        "resolved_audio_url": audio_url,
        "refresh_error": refresh_error,
        "attempts": attempts,
    }


@router.post("/{call_id}/transcribe", response_model=TranscriptionEnqueueResponse)
async def enqueue_transcription(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = await get_call_for_user(db, call_id, current_user)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if not call.audio_url and not call.mikopbx_cdr_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call has no recording")

    if call.transcription and call.transcription.status == TranscriptionStatus.COMPLETED:
        return TranscriptionEnqueueResponse(
            transcription_id=call.transcription.id,
            status=call.transcription.status,
        )

    if call.transcription and call.transcription.status == TranscriptionStatus.PROCESSING:
        return TranscriptionEnqueueResponse(
            transcription_id=call.transcription.id,
            status=call.transcription.status,
        )

    if call.transcription and call.transcription.status == TranscriptionStatus.PENDING:
        celery_app.send_task("transcribe_call", args=[call.transcription.id])
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
    celery_app.send_task("transcribe_call", args=[transcription.id])
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
    _mark_stale_transcription(call.transcription)
    await db.commit()
    await db.refresh(call.transcription)
    return _transcription_to_response(call.transcription)
