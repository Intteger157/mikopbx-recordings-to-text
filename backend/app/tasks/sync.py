from __future__ import annotations

import asyncio
from datetime import datetime

from app.database import async_session
from app.services.sync_service import get_pbx_client, sync_cdr, sync_extensions
from app.tasks.celery_app import celery_app


async def _run_sync(date_from: str, date_to: str) -> dict:
    async with async_session() as db:
        client = await get_pbx_client(db)
        if not client:
            raise RuntimeError("MikoPBX is not configured")

        date_from_dt = datetime.fromisoformat(date_from)
        date_to_dt = datetime.fromisoformat(date_to)
        extensions_synced = await sync_extensions(db, client)
        calls_synced, calls_skipped = await sync_cdr(db, client, date_from_dt, date_to_dt)
        return {
            "extensions_synced": extensions_synced,
            "calls_synced": calls_synced,
            "calls_skipped": calls_skipped,
        }


@celery_app.task(name="sync_pbx")
def sync_pbx_task(date_from: str, date_to: str) -> dict:
    return asyncio.run(_run_sync(date_from, date_to))
