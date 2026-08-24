from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord
from app.services.mikopbx_client import MikoPBXClient


async def resolve_call_audio_url(
    db: AsyncSession,
    client: MikoPBXClient,
    call: CallRecord,
) -> str:
    if call.mikopbx_cdr_id:
        fresh_url = await client.get_cdr_recording_url(call.mikopbx_cdr_id)
        if fresh_url:
            call.audio_url = fresh_url
            await db.commit()
            return fresh_url

    if call.audio_url:
        return call.audio_url

    raise RuntimeError("Call recording URL is missing")
