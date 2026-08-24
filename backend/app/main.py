from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.calls import router as calls_router
from app.api.users import router as users_router
from app.config import get_settings
from app.database import async_session
from app.services.seed import seed_superadmin

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session() as db:
        await seed_superadmin(db)
    yield


app = FastAPI(title="Call Recording Management", version="1.0.0", lifespan=lifespan)

origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(calls_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
