from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from celery.signals import worker_ready
from faster_whisper import WhisperModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import async_session
from app.database_sync import sync_session
from app.models import Transcription
from app.models.enums import TranscriptionStatus
from app.services.recording_service import resolve_call_audio_url
from app.services.sync_service import get_pbx_client
from app.tasks.celery_app import celery_app
from app.tasks.celery_async import run_async_task

settings = get_settings()
_model: WhisperModel | None = None


def get_whisper_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
            cpu_threads=settings.WHISPER_CPU_THREADS,
        )
    return _model


async def _run_transcription(transcription_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Transcription)
            .options(selectinload(Transcription.call_record))
            .where(Transcription.id == transcription_id)
        )
        transcription = result.scalar_one_or_none()
        if not transcription:
            return

        if transcription.status in {TranscriptionStatus.PROCESSING, TranscriptionStatus.COMPLETED}:
            return

        transcription.status = TranscriptionStatus.PROCESSING
        await db.commit()

        temp_path: Path | None = None
        try:
            call = transcription.call_record
            if not call:
                raise RuntimeError("Call record is missing")

            client = await get_pbx_client(db)
            if not client:
                raise RuntimeError("MikoPBX is not configured")

            audio_url = await resolve_call_audio_url(db, client, call)
            suffix = Path(audio_url.split("?", 1)[0]).suffix or ".webm"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp_path = Path(temp_file.name)
            temp_file.close()
            audio_bytes, _ = await client.fetch_recording_bytes(
                audio_url,
                recordingfile=call.recordingfile,
                cdr_id=call.mikopbx_cdr_id,
                read_timeout=180.0,
            )
            temp_path.write_bytes(audio_bytes)

            model = get_whisper_model()
            segments_iter, info = model.transcribe(str(temp_path), vad_filter=True)

            segments = []
            text_parts = []
            for segment in segments_iter:
                segments.append({"start": segment.start, "end": segment.end, "text": segment.text.strip()})
                text_parts.append(segment.text.strip())

            transcription.text = " ".join(part for part in text_parts if part)
            transcription.segments_json = segments
            transcription.language = info.language
            transcription.status = TranscriptionStatus.COMPLETED
            transcription.completed_at = datetime.now(timezone.utc)
            transcription.error_message = None
        except Exception as exc:
            transcription.status = TranscriptionStatus.FAILED
            transcription.error_message = str(exc)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            await db.commit()


@celery_app.task(name="transcribe_call", bind=True, max_retries=0, soft_time_limit=3600, time_limit=3660)
def transcribe_call(self, transcription_id: int) -> None:
    run_async_task(lambda: _run_transcription(transcription_id))


def _release_orphaned_transcriptions_sync() -> None:
    with sync_session() as db:
        result = db.execute(select(Transcription).where(Transcription.status == TranscriptionStatus.PROCESSING))
        for transcription in result.scalars():
            transcription.status = TranscriptionStatus.FAILED
            transcription.error_message = "Worker restarted while transcribing. Press Transcribe to retry."
        db.commit()


@worker_ready.connect
def release_orphaned_transcriptions(**_kwargs) -> None:
    _release_orphaned_transcriptions_sync()
