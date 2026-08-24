from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord, MikoPBXConfig, MikoPBXExtension
from app.services.mikopbx_client import MikoPBXClient
from app.utils.timezone import parse_pbx_local_datetime

ProgressCallback = Callable[[dict[str, Any]], None]


async def get_pbx_client(db: AsyncSession) -> MikoPBXClient | None:
    result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config or not config.api_url or not config.api_key:
        return None
    return MikoPBXClient(config.api_url, config.api_key)


def parse_call_date(value: str) -> datetime:
    return parse_pbx_local_datetime(value)


def _leg_to_payload(leg: dict[str, Any], ext_map: dict[str, str]) -> dict[str, Any] | None:
    audio_url = leg.get("download_url") or leg.get("playback_url")
    uniqueid = leg.get("UNIQUEID") or leg.get("uniqueid")

    if not uniqueid or not audio_url:
        return None

    recordingfile = leg.get("recordingfile")

    start = leg.get("_group_start") or leg.get("start")
    call_date = parse_call_date(start) if start else datetime.now(timezone.utc)

    src_num = leg.get("src_num") or leg.get("_group_src")
    dst_num = leg.get("dst_num") or leg.get("_group_dst")
    src_name = leg.get("src_name") or leg.get("_group_src_name")
    dst_name = leg.get("dst_name") or leg.get("_group_dst_name")
    src_str = str(src_num) if src_num is not None else None
    dst_str = str(dst_num) if dst_num is not None else None

    employee_name = None
    for number in (src_str, dst_str):
        if number and number in ext_map:
            employee_name = ext_map[number]
            break

    cdr_id = leg.get("id")
    mikopbx_cdr_id = int(cdr_id) if cdr_id is not None else None

    return {
        "uniqueid": uniqueid,
        "linkedid": leg.get("linkedid") or leg.get("_group_linkedid"),
        "call_date": call_date,
        "src_num": src_str,
        "dst_num": dst_str,
        "duration": int(leg.get("duration") or leg.get("_group_duration") or 0),
        "billsec": int(leg.get("billsec") or leg.get("_group_billsec") or 0),
        "audio_url": audio_url,
        "recordingfile": recordingfile,
        "mikopbx_cdr_id": mikopbx_cdr_id,
        "miko_user_name": employee_name or src_name or dst_name,
        "disposition": leg.get("disposition") or leg.get("_group_disposition"),
    }


def _report(progress: ProgressCallback | None, **fields: Any) -> None:
    if progress:
        progress(fields)


def _iter_date_chunks(date_from: datetime, date_to: datetime, chunk_days: int = 3) -> Iterator[tuple[datetime, datetime]]:
    current = date_from
    while current <= date_to:
        chunk_end = min(current + timedelta(days=chunk_days) - timedelta(seconds=1), date_to)
        yield current, chunk_end
        next_start = chunk_end + timedelta(seconds=1)
        if next_start > date_to:
            break
        current = next_start


async def sync_extensions(
    db: AsyncSession,
    client: MikoPBXClient,
    progress: ProgressCallback | None = None,
) -> int:
    _report(progress, phase="extensions", message="Fetching employees from MikoPBX...")
    employees = await client.get_all_employees()
    now = datetime.now(timezone.utc)

    result = await db.execute(select(MikoPBXExtension))
    existing = {row.extension: row for row in result.scalars()}

    count = 0
    for employee in employees:
        extension = str(employee.get("number") or "").strip()
        if not extension:
            continue

        display_name = employee.get("user_username") or employee.get("name") or extension
        employee_id = str(employee.get("id")) if employee.get("id") is not None else None
        row = existing.get(extension)

        if row:
            row.display_name = display_name
            row.employee_id = employee_id
            row.synced_at = now
        else:
            db.add(
                MikoPBXExtension(
                    extension=extension,
                    display_name=display_name,
                    employee_id=employee_id,
                    synced_at=now,
                )
            )
        count += 1

    await db.commit()
    _report(progress, extensions_synced=count, message=f"Synced {count} extensions")
    return count


async def _upsert_call_batch(db: AsyncSession, batch: list[dict[str, Any]]) -> None:
    if not batch:
        return

    stmt = insert(CallRecord).values(batch)
    update_columns = {
        "linkedid": stmt.excluded.linkedid,
        "call_date": stmt.excluded.call_date,
        "src_num": stmt.excluded.src_num,
        "dst_num": stmt.excluded.dst_num,
        "duration": stmt.excluded.duration,
        "billsec": stmt.excluded.billsec,
        "audio_url": stmt.excluded.audio_url,
        "recordingfile": stmt.excluded.recordingfile,
        "mikopbx_cdr_id": stmt.excluded.mikopbx_cdr_id,
        "miko_user_name": stmt.excluded.miko_user_name,
        "disposition": stmt.excluded.disposition,
    }
    stmt = stmt.on_conflict_do_update(index_elements=["uniqueid"], set_=update_columns)
    await db.execute(stmt)


async def sync_cdr(
    db: AsyncSession,
    client: MikoPBXClient,
    date_from: datetime,
    date_to: datetime,
    progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    synced = 0
    skipped = 0
    limit = 50
    page_num = 0
    total_chunks = max(1, (date_to - date_from).days // 3 + 1)
    chunk_index = 0

    ext_result = await db.execute(select(MikoPBXExtension))
    ext_map = {row.extension: row.display_name for row in ext_result.scalars()}

    _report(progress, phase="cdr", message="Fetching call recordings from MikoPBX...")

    for chunk_from, chunk_to in _iter_date_chunks(date_from, date_to, chunk_days=3):
        chunk_index += 1
        chunk_label = f"{chunk_from.date()} — {chunk_to.date()}"
        offset = 0
        last_id: int | None = None

        _report(
            progress,
            phase="cdr",
            message=f"CDR period {chunk_index}/{total_chunks}: {chunk_label}",
        )

        while True:
            page_num += 1
            _report(
                progress,
                phase="cdr",
                cdr_page=page_num,
                calls_synced=synced,
                calls_skipped=skipped,
                message=f"Fetching CDR page {page_num} ({chunk_label})...",
            )

            page = await client.get_cdr_page(
                date_from=chunk_from,
                date_to=chunk_to,
                offset=offset,
                limit=limit,
                last_id=last_id,
            )
            legs, has_more, pagination = client.parse_cdr_page(page, limit=limit)

            batch: list[dict[str, Any]] = []
            for leg in legs:
                payload = _leg_to_payload(leg, ext_map)
                if payload is None:
                    skipped += 1
                    continue
                batch.append(payload)
                synced += 1

            await _upsert_call_batch(db, batch)
            await db.commit()

            _report(
                progress,
                phase="cdr",
                cdr_page=page_num,
                calls_synced=synced,
                calls_skipped=skipped,
                message=f"Imported {synced} recordings ({skipped} skipped) · page {page_num}",
            )

            if pagination and pagination.get("lastId") is not None:
                try:
                    last_id = int(pagination["lastId"])
                except (TypeError, ValueError):
                    last_id = None

            if not has_more:
                break
            offset += limit

    config_result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = config_result.scalar_one()
    config.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    return synced, skipped
