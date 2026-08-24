from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models import MikoPBXConfig, User
from app.models.enums import UserRole
from app.config import get_settings


async def seed_superadmin(db: AsyncSession) -> None:
    settings = get_settings()
    result = await db.execute(select(User).where(User.username == settings.SUPERADMIN_USERNAME))
    if result.scalar_one_or_none() is None:
        admin = User(
            username=settings.SUPERADMIN_USERNAME,
            email=settings.SUPERADMIN_EMAIL,
            hashed_password=get_password_hash(settings.SUPERADMIN_PASSWORD),
            role=UserRole.SUPERADMIN,
            is_active=True,
        )
        db.add(admin)

    config_result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    if config_result.scalar_one_or_none() is None:
        db.add(MikoPBXConfig(id=1, api_url=None, api_key=None, is_connected=False, last_sync_at=None))

    await db.commit()
