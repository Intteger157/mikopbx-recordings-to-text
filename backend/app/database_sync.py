from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()

sync_engine = create_engine(settings.DATABASE_URL_SYNC, echo=False, pool_pre_ping=True)
sync_session = sessionmaker(sync_engine, expire_on_commit=False)
