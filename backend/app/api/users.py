from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_roles
from app.core.security import get_password_hash
from app.database import get_db
from app.models import User, UserExtension
from app.models.enums import UserRole
from app.schemas import UserCreate, UserResponse, UserUpdate
from app.services.user_service import user_to_response

router = APIRouter(prefix="/api/users", tags=["users"])


async def _set_extensions(db: AsyncSession, user: User, extensions: list[str]) -> None:
    user.allowed_extensions[:] = [
        UserExtension(extension=extension) for extension in sorted(set(extensions))
    ]


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    result = await db.execute(select(User).options(selectinload(User.allowed_extensions)).order_by(User.id))
    users = result.scalars().all()
    return [user_to_response(user) for user in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    existing = await db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username or email already exists")

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    await _set_extensions(db, user, payload.allowed_extensions)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    result = await db.execute(
        select(User).options(selectinload(User.allowed_extensions)).where(User.id == user.id)
    )
    return user_to_response(result.scalar_one())


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    result = await db.execute(
        select(User).options(selectinload(User.allowed_extensions)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = get_password_hash(payload.password)
    if payload.allowed_extensions is not None:
        await _set_extensions(db, user, payload.allowed_extensions)

    await db.commit()
    await db.refresh(user)
    return user_to_response(user)


@router.delete("/{user_id}", response_model=UserResponse)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPERADMIN)),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    result = await db.execute(
        select(User).options(selectinload(User.allowed_extensions)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    await db.commit()
    return user_to_response(user)
