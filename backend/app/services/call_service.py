from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CallRecord, User
from app.models.enums import UserRole


def get_user_extensions(user: User) -> list[str]:
    return [ext.extension for ext in user.allowed_extensions]


def apply_call_rbac_filter(stmt, user: User):
    if user.role == UserRole.SUPERADMIN:
        return stmt

    extensions = get_user_extensions(user)
    if not extensions:
        return stmt.where(CallRecord.id == -1)

    return stmt.where(or_(CallRecord.src_num.in_(extensions), CallRecord.dst_num.in_(extensions)))


async def get_call_for_user(db: AsyncSession, call_id: int, user: User) -> CallRecord | None:
    stmt = select(CallRecord).options(selectinload(CallRecord.transcription)).where(CallRecord.id == call_id)
    stmt = apply_call_rbac_filter(stmt, user)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
