from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings


def get_pbx_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().PBX_TIMEZONE)


def parse_pbx_local_datetime(value: str) -> datetime:
    """Parse MikoPBX datetime (local PBX time, no offset) and store as UTC."""
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=get_pbx_timezone()).astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def localize_naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=get_pbx_timezone()).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)
