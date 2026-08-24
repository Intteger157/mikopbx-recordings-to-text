from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _cache_dir() -> Path:
    path = Path(settings.RECORDINGS_CACHE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(call_id: int, recordingfile: str | None) -> Path:
    suffix = Path(recordingfile or "").suffix or ".webm"
    return _cache_dir() / f"{call_id}{suffix}"


def read_recording(call_id: int, recordingfile: str | None) -> tuple[bytes, str | None] | None:
    """Return a previously downloaded recording.

    Downloading from MikoPBX costs hundreds of ranged requests and runs into
    rate limits, so a recording is fetched once and reused by both the player
    and the transcription worker.
    """
    path = _cache_path(call_id, recordingfile)
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        return path.read_bytes(), mimetypes.guess_type(path.name)[0]
    except OSError as exc:
        logger.warning("Cannot read cached recording %s: %s", path, exc)
        return None


def write_recording(call_id: int, recordingfile: str | None, data: bytes) -> None:
    path = _cache_path(call_id, recordingfile)
    try:
        temp = path.with_suffix(path.suffix + ".part")
        temp.write_bytes(data)
        temp.replace(path)
    except OSError as exc:
        logger.warning("Cannot cache recording %s: %s", path, exc)
