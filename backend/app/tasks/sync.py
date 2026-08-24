from __future__ import annotations

from datetime import datetime

from app.database import async_session
from app.services.sync_service import get_pbx_client, sync_cdr, sync_extensions
from app.services.sync_status import complete_sync, fail_sync, update_sync_status
from app.tasks.celery_app import celery_app
from app.tasks.celery_async import run_async_task


def _progress_callback(fields: dict) -> None:
    update_sync_status(**fields)


async def _run_sync(date_from: str, date_to: str) -> dict:
    try:
        async with async_session() as db:
            client = await get_pbx_client(db)
            if not client:
                raise RuntimeError("MikoPBX is not configured")

            date_from_dt = datetime.fromisoformat(date_from)
            date_to_dt = datetime.fromisoformat(date_to)

            extensions_synced = await sync_extensions(db, client, progress=_progress_callback)
            calls_synced, calls_skipped = await sync_cdr(
                db, client, date_from_dt, date_to_dt, progress=_progress_callback
            )

        complete_sync(extensions_synced, calls_synced, calls_skipped)
        return {
            "extensions_synced": extensions_synced,
            "calls_synced": calls_synced,
            "calls_skipped": calls_skipped,
        }
    except Exception as exc:
        fail_sync(str(exc))
        raise


@celery_app.task(name="sync_pbx", bind=True, max_retries=0, soft_time_limit=3600, time_limit=3660)
def sync_pbx_task(self, date_from: str, date_to: str) -> dict:
    return run_async_task(lambda: _run_sync(date_from, date_to))
