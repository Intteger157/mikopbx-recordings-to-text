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
from app.models import CallRecord, MikoPBXConfig, Transcription
from app.models.enums import TranscriptionStatus
from app.services.mikopbx_client import MikoPBXClient
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


async def _get_pbx_client():
    async with async_session() as db:
        result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
        config = result.scalar_one_or_none()
        if not config or not config.api_url or not config.api_key:
            raise RuntimeError("MikoPBX is not configured")
        return MikoPBXClient(config.api_url, config.api_key)


async def _download_audio(client: MikoPBXClient, audio_url: str) -> Path:
    url = client.resolve_audio_url(audio_url)
    suffix = Path(audio_url.split("?", 1)[0]).suffix or ".webm"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    temp_file.close()

    async with httpx.AsyncClient(timeout=120.0, verify=False) as http_client:
        async with http_client.stream("GET", url, headers=client._headers()) as response:
            response.raise_for_status()
            with temp_path.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
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

        transcription.status = TranscriptionStatus.PROCESSING
        await db.commit()

        temp_path: Path | None = None
        try:
            call = transcription.call_record
            if not call or not call.audio_url:
                raise RuntimeError("Call recording is missing")

            client = await _get_pbx_client()
            temp_path = await _download_audio(client, call.audio_url)

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


@celery_app.task(name="transcribe_call")
def transcribe_call(transcription_id: int) -> None:
    asyncio.run(_run_transcription(transcription_id))
