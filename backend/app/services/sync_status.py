from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis

from app.config import get_settings

SYNC_STATUS_KEY = "whisper:pbx_sync_status"


def _redis_client() -> redis.Redis:
    return redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def default_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "phase": None,
        "extensions_synced": 0,
        "calls_synced": 0,
        "calls_skipped": 0,
        "cdr_page": 0,
        "message": "No sync in progress",
        "error": None,
        "started_at": None,
        "finished_at": None,
    }


def get_sync_status() -> dict[str, Any]:
    raw = _redis_client().get(SYNC_STATUS_KEY)
    if not raw:
        return default_status()
    return json.loads(raw)


def start_sync() -> dict[str, Any]:
    status = {
        "state": "running",
        "phase": "starting",
        "extensions_synced": 0,
        "calls_synced": 0,
        "calls_skipped": 0,
        "cdr_page": 0,
        "message": "Starting sync...",
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    _redis_client().set(SYNC_STATUS_KEY, json.dumps(status), ex=7200)
    return status


def update_sync_status(**fields: Any) -> dict[str, Any]:
    status = get_sync_status()
    if status.get("state") == "idle":
        status = start_sync()
    status.update(fields)
    _redis_client().set(SYNC_STATUS_KEY, json.dumps(status), ex=7200)
    return status


def complete_sync(extensions_synced: int, calls_synced: int, calls_skipped: int) -> dict[str, Any]:
    status = get_sync_status()
    status.update(
        {
            "state": "completed",
            "phase": "done",
            "extensions_synced": extensions_synced,
            "calls_synced": calls_synced,
            "calls_skipped": calls_skipped,
            "message": f"Done: {calls_synced} calls with recordings imported",
            "error": None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _redis_client().set(SYNC_STATUS_KEY, json.dumps(status), ex=7200)
    return status


def fail_sync(error: str) -> dict[str, Any]:
    status = get_sync_status()
    status.update(
        {
            "state": "failed",
            "phase": "error",
            "message": "Sync failed",
            "error": error,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _redis_client().set(SYNC_STATUS_KEY, json.dumps(status), ex=7200)
    return status


def is_sync_running() -> bool:
    return get_sync_status().get("state") == "running"
