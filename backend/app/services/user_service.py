from app.models import User


def user_to_response(user: User):
    from app.schemas import UserResponse

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        allowed_extensions=[ext.extension for ext in user.allowed_extensions],
    )
