from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CallRecord, MikoPBXConfig, MikoPBXExtension
from app.services.mikopbx_client import MikoPBXClient


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


async def sync_extensions(db: AsyncSession, client: MikoPBXClient) -> int:
    employees = await client.get_all_employees()
    count = 0
    now = datetime.now(timezone.utc)

    for employee in employees:
        extension = str(employee.get("number") or "").strip()
        if not extension:
            continue

        result = await db.execute(
            select(MikoPBXExtension).where(MikoPBXExtension.extension == extension)
        )
        row = result.scalar_one_or_none()
        display_name = employee.get("user_username") or employee.get("name") or extension
        employee_id = str(employee.get("id")) if employee.get("id") is not None else None

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
    return count


async def sync_cdr(
    db: AsyncSession,
    client: MikoPBXClient,
    date_from: datetime,
    date_to: datetime,
) -> tuple[int, int]:
    synced = 0
    skipped = 0
    offset = 0
    limit = 100

    ext_result = await db.execute(select(MikoPBXExtension))
    ext_map = {row.extension: row.display_name for row in ext_result.scalars()}

    while True:
        page = await client.get_cdr_page(date_from=date_from, date_to=date_to, offset=offset, limit=limit)
        page_data = page.get("data")
        if not isinstance(page_data, dict):
            break
        records = page_data.get("records", [])
        if not isinstance(records, list):
            records = []

        for group in records:
            group_start = group.get("start")
            group_src = group.get("src_num")
            group_dst = group.get("dst_num")
            linkedid = group.get("linkedid")

            for leg in group.get("records", []):
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

                result = await db.execute(select(CallRecord).where(CallRecord.uniqueid == uniqueid))
                existing = result.scalar_one_or_none()

                payload = {
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

                if existing:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                else:
                    db.add(CallRecord(uniqueid=uniqueid, **payload))
                synced += 1

        pagination = page_data.get("pagination", {}) if isinstance(page_data, dict) else {}
        if not pagination.get("hasMore"):
            break
        offset += limit

    config_result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = config_result.scalar_one()
    config.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    return synced, skipped
