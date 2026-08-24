from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from faster_whisper import WhisperModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import async_session
from app.models import Transcription
from app.models.enums import TranscriptionStatus
from app.services.mikopbx_client import MikoPBXClient
from app.services.recording_service import resolve_call_audio_url
from app.services.sync_service import get_pbx_client
from app.tasks.celery_app import celery_app

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


async def _download_audio(client: MikoPBXClient, audio_url: str) -> Path:
    url = client.resolve_audio_url(audio_url)
    suffix = Path(audio_url.split("?", 1)[0]).suffix or ".webm"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    temp_file.close()

    timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, verify=False) as http_client:
        response = await http_client.get(url, headers=client._headers())
        if response.status_code >= 400 and "token=" in url:
            response = await http_client.get(url)
        response.raise_for_status()
        temp_path.write_bytes(response.content)
    return temp_path


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
            temp_path = await _download_audio(client, audio_url)

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
    asyncio.run(_run_transcription(transcription_id))
