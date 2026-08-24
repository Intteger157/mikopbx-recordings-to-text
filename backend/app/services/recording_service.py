from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord
from app.services.mikopbx_client import MikoPBXClient
from app.services.recording_cache import read_recording, write_recording
from app.utils.timezone import get_pbx_timezone


LOOKUP_PAGE_SIZE = 100
MAX_LOOKUP_PAGES = 10


def _leg_uniqueid(leg: dict) -> str | None:
    return leg.get("UNIQUEID") or leg.get("uniqueid")


def _leg_recording_url(leg: dict) -> str | None:
    return MikoPBXClient.find_recording_url(leg)


def _match_leg(legs: list[dict], call: CallRecord) -> dict | None:
    for leg in legs:
        if _leg_uniqueid(leg) == call.uniqueid:
            return leg
    if call.mikopbx_cdr_id:
        for leg in legs:
            if str(leg.get("id")) == str(call.mikopbx_cdr_id):
                return leg
    return None


async def _lookup_cdr_leg(client: MikoPBXClient, call: CallRecord) -> dict | None:
    """Find the CDR leg for this call to get a fresh recording token.

    This PBX ignores the time part of ``dateFrom``/``dateTo`` and returns
    nothing for a sub-day window, so search the whole call day and narrow it
    down with the caller number instead.
    """
    tz = get_pbx_timezone()
    local = call.call_date.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    for src_num in (call.src_num, None):
        offset = 0
        last_id: int | None = None

        for _ in range(MAX_LOOKUP_PAGES):
            try:
                page = await client.get_cdr_page(
                    date_from=day_start,
                    date_to=day_end,
                    offset=offset,
                    limit=LOOKUP_PAGE_SIZE,
                    last_id=last_id,
                    src_num=src_num,
                )
            except RuntimeError:
                break

            legs, has_more, pagination = client.parse_cdr_page(page, limit=LOOKUP_PAGE_SIZE)
            if not legs:
                break

            match = _match_leg(legs, call)
            if match:
                return match
            if not has_more:
                break

            offset += LOOKUP_PAGE_SIZE
            last_id = pagination.get("lastId") if isinstance(pagination, dict) else None

        if not src_num:
            break

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
    """Get a usable recording URL, renewing the playback token when possible.

    Tokens stored at sync time expire, so the CDR listing is the source of
    truth; ``/cdr/{id}`` is only a fallback because some builds answer it with
    an empty payload.
    """
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

    if call.mikopbx_cdr_id:
        try:
            fresh_url = await client.get_cdr_recording_url(call.mikopbx_cdr_id)
        except RuntimeError:
            fresh_url = None
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
    """Return a call recording, downloading it from MikoPBX only once.

    Playback tokens stored at sync time expire, so the token is renewed on
    demand, and the downloaded file is cached because MikoPBX needs hundreds of
    ranged requests per recording and rate limits them.
    """
    cached = read_recording(call.id, call.recordingfile)
    if cached:
        return cached

    audio_url = await resolve_call_audio_url(db, client, call)
    try:
        data, content_type = await client.fetch_recording_bytes(
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
            raise RuntimeError("MikoPBX playback token expired and could not be renewed") from exc

        data, content_type = await client.fetch_recording_bytes(
            refreshed,
            recordingfile=call.recordingfile,
            cdr_id=call.mikopbx_cdr_id,
            read_timeout=read_timeout,
            max_urls=max_urls,
        )

    write_recording(call.id, call.recordingfile, data)
    return data, content_type
