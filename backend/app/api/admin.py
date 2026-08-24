from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models import MikoPBXConfig, MikoPBXExtension, User
from app.models.enums import UserRole
from app.schemas import (
    ExtensionResponse,
    PBXConfigResponse,
    PBXConfigUpdate,
    PBXSyncRequest,
    PBXSyncResponse,
)
from app.services.sync_service import get_pbx_client, sync_cdr, sync_extensions
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/pbx-config", response_model=PBXConfigResponse)
async def get_pbx_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = result.scalar_one()
    return PBXConfigResponse(
        api_url=config.api_url,
        has_api_key=bool(config.api_key),
        is_connected=config.is_connected,
        last_sync_at=config.last_sync_at,
    )


@router.put("/pbx-config", response_model=PBXConfigResponse)
async def update_pbx_config(
    payload: PBXConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = result.scalar_one()
    config.api_url = payload.api_url.rstrip("/")
    if payload.api_key:
        config.api_key = payload.api_key
    config.is_connected = False
    await db.commit()
    return PBXConfigResponse(
        api_url=config.api_url,
        has_api_key=bool(config.api_key),
        is_connected=config.is_connected,
        last_sync_at=config.last_sync_at,
    )


@router.post("/pbx-config/test")
async def test_pbx_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    client = await get_pbx_client(db)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MikoPBX is not configured")

    try:
        await client.check_auth()
    except Exception as exc:
        result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
        config = result.scalar_one()
        config.is_connected = False
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    result = await db.execute(select(MikoPBXConfig).where(MikoPBXConfig.id == 1))
    config = result.scalar_one()
    config.is_connected = True
    await db.commit()
    return {"success": True, "message": "Connection successful"}


@router.post("/pbx-config/sync", response_model=PBXSyncResponse)
async def trigger_pbx_sync(
    payload: PBXSyncRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    client = await get_pbx_client(db)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MikoPBX is not configured")

    try:
        extensions_synced = await sync_extensions(db, client)
        calls_synced, calls_skipped = await sync_cdr(db, client, payload.date_from, payload.date_to)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return PBXSyncResponse(
        extensions_synced=extensions_synced,
        calls_synced=calls_synced,
        calls_skipped=calls_skipped,
    )


@router.post("/pbx-config/sync-async")
async def trigger_pbx_sync_async(
    payload: PBXSyncRequest,
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    celery_app.send_task(
        "sync_pbx",
        args=[payload.date_from.isoformat(), payload.date_to.isoformat()],
    )
    return {"success": True, "message": "Sync job queued"}


@router.get("/extensions", response_model=list[ExtensionResponse])
async def list_extensions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    result = await db.execute(select(MikoPBXExtension).order_by(MikoPBXExtension.extension))
    return result.scalars().all()
