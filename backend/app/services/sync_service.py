from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord, MikoPBXConfig, MikoPBXExtension
from app.services.mikopbx_client import MikoPBXClient

ProgressCallback = Callable[[dict[str, Any]], None]


async def get_pbx_client(db: AsyncSession) -> MikoPBXClient | None:
    result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config or not config.api_url or not config.api_key:
        return None
    return MikoPBXClient(config.api_url, config.api_key)


def parse_call_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _report(progress: ProgressCallback | None, **fields: Any) -> None:
    if progress:
        progress(fields)


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
    offset = 0
    limit = 100
    page_num = 0

    ext_result = await db.execute(select(MikoPBXExtension))
    ext_map = {row.extension: row.display_name for row in ext_result.scalars()}

    _report(progress, phase="cdr", message="Fetching call recordings from MikoPBX...")

    while True:
        page_num += 1
        _report(
            progress,
            phase="cdr",
            cdr_page=page_num,
            calls_synced=synced,
            calls_skipped=skipped,
            message=f"Fetching CDR page {page_num}...",
        )

        page = await client.get_cdr_page(date_from=date_from, date_to=date_to, offset=offset, limit=limit)
        page_data = page.get("data")
        if not isinstance(page_data, dict):
            break

        records = page_data.get("records", [])
        if not isinstance(records, list):
            records = []

        batch: list[dict[str, Any]] = []

        for group in records:
            group_start = group.get("start")
            group_src = group.get("src_num")
            group_dst = group.get("dst_num")
            linkedid = group.get("linkedid")
            legs = group.get("records", [])
            if not isinstance(legs, list):
                continue

            for leg in legs:
                recordingfile = leg.get("recordingfile")
                playback_url = leg.get("playback_url") or leg.get("download_url")
                uniqueid = leg.get("UNIQUEID") or leg.get("uniqueid")

                if not uniqueid or not recordingfile or not playback_url:
                    skipped += 1
                    continue

                call_date = parse_call_date(group_start) if group_start else datetime.now(timezone.utc)
                src_num = leg.get("src_num") or group_src
                dst_num = leg.get("dst_num") or group_dst
                src_name = group.get("src_name")
                dst_name = group.get("dst_name")
                src_str = str(src_num) if src_num is not None else None
                dst_str = str(dst_num) if dst_num is not None else None
                employee_name = None
                for number in (src_str, dst_str):
                    if number and number in ext_map:
                        employee_name = ext_map[number]
                        break

                batch.append(
                    {
                        "uniqueid": uniqueid,
                        "linkedid": linkedid,
                        "call_date": call_date,
                        "src_num": src_str,
                        "dst_num": dst_str,
                        "duration": int(leg.get("duration") or group.get("totalDuration") or 0),
                        "billsec": int(leg.get("billsec") or group.get("totalBillsec") or 0),
                        "audio_url": playback_url,
                        "recordingfile": recordingfile,
                        "miko_user_name": employee_name or src_name or dst_name,
                        "disposition": leg.get("disposition") or group.get("disposition"),
                    }
                )
                synced += 1

        await _upsert_call_batch(db, batch)
        await db.commit()

        _report(
            progress,
            phase="cdr",
            cdr_page=page_num,
            calls_synced=synced,
            calls_skipped=skipped,
            message=f"Imported {synced} recordings so far (page {page_num})",
        )

        pagination = page_data.get("pagination", {})
        if not isinstance(pagination, dict) or not pagination.get("hasMore"):
            break
        offset += limit

    config_result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = config_result.scalar_one()
    config.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    return synced, skipped
