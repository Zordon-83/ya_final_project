from asyncio import to_thread

import jwt
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from schemas.user import AuthData, AuthToken

from core.auth_errors import auth_unavailable
from core.exceptions import CustomException
from core.security import create_access_token, decode_access_token, verify_password
from core.sessions import RedisSessionStore
from core.settings import Settings


async def login_user(
    session: AsyncSession,
    credentials: AuthData,
    config: Settings,
    store: RedisSessionStore,
) -> AuthToken:
    """Проверяет учётные данные и выдаёт токен активному пользователю."""
    if config.jwt_secret_key is None:
        raise CustomException(
            code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message='Вход временно недоступен',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    login = str(credentials.login)
    condition = func.lower(User.email) == login.lower() if '@' in login else User.phone == login
    # Общая с изменением пароля/блокировкой блокировка исключает выдачу старой сессии после отзыва.
    candidates = (
        await session.scalars(select(User).where(condition).order_by(User.id).limit(2).with_for_update())
    ).all()
    user = candidates[0] if len(candidates) == 1 else None
    valid_password = await to_thread(
        verify_password,
        credentials.password,
        user.password_hash if user is not None else None,
    )
    if user is None or not valid_password or not user.is_active:
        raise CustomException(
            code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message='Неверные имя пользователя или пароль',
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    token = create_access_token(user.id, user.role, config)
    try:
        claims = decode_access_token(token, config)
    except jwt.InvalidTokenError:
        raise auth_unavailable() from None
    await store.create(claims['jti'], user.id, claims['exp'])
    await session.commit()
    return AuthToken(access_token=token, token_type='bearer')
