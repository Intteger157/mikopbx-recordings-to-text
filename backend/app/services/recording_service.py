from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord
from app.services.mikopbx_client import MikoPBXClient
from app.utils.timezone import get_pbx_timezone


def _leg_uniqueid(leg: dict) -> str | None:
    return leg.get("UNIQUEID") or leg.get("uniqueid")


def _leg_recording_url(leg: dict) -> str | None:
    return MikoPBXClient.find_recording_url(leg)


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
    if call.mikopbx_cdr_id:
        for leg in legs:
            if str(leg.get("id")) == str(call.mikopbx_cdr_id):
                return leg
    return None


def _normalize_stored_url(
    client: MikoPBXClient,
    raw_url: str | None,
    recordingfile: str | None,
    cdr_id: int | None = None,
) -> str | None:
    token = client.extract_recording_token(raw_url or "")
    if not token:
        return raw_url
    if raw_url and (":download" in raw_url or ":playback" in raw_url):
        return client.resolve_audio_url(raw_url)
    return client.build_recording_download_url(token, recordingfile, cdr_id)


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
            call.audio_url = _normalize_stored_url(client, fresh_url, call.recordingfile, call.mikopbx_cdr_id) or fresh_url
            await db.commit()
            return call.audio_url

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
            call.audio_url = _normalize_stored_url(client, fresh_url, call.recordingfile, call.mikopbx_cdr_id) or fresh_url
            await db.commit()
            return call.audio_url

    normalized = _normalize_stored_url(client, call.audio_url, call.recordingfile, call.mikopbx_cdr_id)
    if normalized and normalized != call.audio_url:
        call.audio_url = normalized
        await db.commit()
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


def _is_expired_token_error(message: str) -> bool:
    lowered = message.lower()
    return "expired" in lowered or "invalid or expired playback token" in lowered


async def fetch_call_recording(
    db: AsyncSession,
    client: MikoPBXClient,
    call: CallRecord,
    read_timeout: float = 60.0,
    max_urls: int | None = None,
) -> tuple[bytes, str | None]:
    """Download a call recording, renewing the playback token once if needed.

    MikoPBX playback tokens are short lived, so a token stored at sync time is
    usually rejected by the time somebody opens the call.
    """
    audio_url = await resolve_call_audio_url(db, client, call)
    try:
        return await client.fetch_recording_bytes(
            audio_url,
            recordingfile=call.recordingfile,
            cdr_id=call.mikopbx_cdr_id,
            read_timeout=read_timeout,
            max_urls=max_urls,
        )
    except RuntimeError as exc:
        if not _is_expired_token_error(str(exc)):
            raise

    call.audio_url = None
    refreshed = await refresh_call_recording(db, client, call)
    if not refreshed or refreshed == audio_url:
        raise RuntimeError("MikoPBX playback token expired and could not be renewed")

    return await client.fetch_recording_bytes(
        refreshed,
        recordingfile=call.recordingfile,
        cdr_id=call.mikopbx_cdr_id,
        read_timeout=read_timeout,
        max_urls=max_urls,
    )
