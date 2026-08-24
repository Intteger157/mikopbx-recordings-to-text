from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord
from app.services.mikopbx_client import MikoPBXClient
from app.utils.timezone import get_pbx_timezone


def _leg_uniqueid(leg: dict) -> str | None:
    return leg.get("UNIQUEID") or leg.get("uniqueid")


def _leg_recording_url(leg: dict) -> str | None:
    return leg.get("download_url") or leg.get("playback_url")


async def _lookup_cdr_leg(client: MikoPBXClient, call: CallRecord) -> dict | None:
    """Find the CDR leg for this call to get a fresh recording token.

    Kept to a single narrow page so audio requests never block for minutes.
    """
    tz = get_pbx_timezone()
    center = call.call_date.astimezone(tz)
    page = await client.get_cdr_page(
        date_from=center - timedelta(minutes=15),
        date_to=center + timedelta(minutes=15),
        offset=0,
        limit=100,
    )
    legs, _, _ = client.parse_cdr_page(page, limit=100)
    for leg in legs:
        if _leg_uniqueid(leg) == call.uniqueid:
            return leg
    return None


async def refresh_call_recording(
    db: AsyncSession,
    client: MikoPBXClient,
    call: CallRecord,
) -> str | None:
    if call.mikopbx_cdr_id:
        try:
            fresh_url = await client.get_cdr_recording_url(call.mikopbx_cdr_id)
        except RuntimeError:
            fresh_url = None
        if fresh_url:
            call.audio_url = fresh_url
            await db.commit()
            return fresh_url

    try:
        leg = await _lookup_cdr_leg(client, call)
    except RuntimeError:
        leg = None
    if leg:
        cdr_id = leg.get("id")
        fresh_url = _leg_recording_url(leg)
        if cdr_id is not None:
            call.mikopbx_cdr_id = int(cdr_id)
        if fresh_url:
            call.audio_url = fresh_url
            await db.commit()
            return fresh_url

    return call.audio_url


async def resolve_call_audio_url(
    db: AsyncSession,
    client: MikoPBXClient,
    call: CallRecord,
) -> str:
    url = await refresh_call_recording(db, client, call)
    if url:
        return url
    raise RuntimeError("Call recording URL is missing")
