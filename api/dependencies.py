from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import UserRole
from models.user import User

from core.auth_errors import auth_unavailable, unauthorized
from core.db import get_session
from core.exceptions import CustomException
from core.logging import bind_request_actor
from core.security import decode_access_token
from core.sessions import RedisSessionStore
from core.settings import settings

bearer = HTTPBearer(auto_error=False, scheme_name='bearerAuth', bearerFormat='JWT')


def get_session_store(request: Request) -> RedisSessionStore:
    """Получает Redis-клиент, принадлежащий жизненному циклу приложения."""
    store = getattr(request.app.state, 'session_store', None)
    if store is None:
        raise auth_unavailable()
    return store


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[RedisSessionStore, Depends(get_session_store)],
) -> User:
    """Проверяет JWT, Redis-сессию и актуальную активную запись в PostgreSQL."""
    if credentials is None:
        raise unauthorized()
    if settings.jwt_secret_key is None:
        raise auth_unavailable()
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    if not await store.is_active(claims['jti'], claims['user_id']):
        raise unauthorized()
    user = await session.get(User, claims['user_id'])
    if user is None or not user.is_active:
        raise unauthorized()
    if 'audit_actor' in request.scope:
        bind_request_actor(request.scope, user_id=user.id, username=user.username)
    request.state.auth_session = (store, claims['jti'], user.id, claims['exp'])
    return user


async def registration_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[RedisSessionStore, Depends(get_session_store)],
) -> User | None:
    """Разрешает регистрацию гостю, MANAGER или ADMIN согласно описанию POST /users."""
    if 'authorization' not in request.headers:
        return None
    user = await get_current_user(request, credentials, session, store)
    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise CustomException(
            code=status.HTTP_403_FORBIDDEN,
            message='Недостаточно прав',
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return user


def require_roles(*roles: UserRole) -> Callable[..., Coroutine[Any, Any, User]]:
    """Разрешает только перечисленные роли из БД, не доверяя роли внутри JWT."""

    async def check_role(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise CustomException(
                code=status.HTTP_403_FORBIDDEN,
                message='Недостаточно прав',
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return user

    return check_role
