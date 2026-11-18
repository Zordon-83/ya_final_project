from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session_store
from schemas.user import AuthData, AuthToken
from services.auth import login_user

from core.db import get_session
from core.exceptions import CustomError
from core.sessions import RedisSessionStore
from core.settings import settings

router = APIRouter(prefix='/auth')


@router.post(
    '/login',
    response_model=AuthToken,
    summary='Получение токена авторизации',
    operation_id='get_token_auth_login_post',
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            'model': CustomError,
            'description': 'Неверные имя пользователя или пароль',
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            'model': CustomError,
            'description': 'Вход временно недоступен',
        },
    },
)
async def login(
    credentials: AuthData,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[RedisSessionStore, Depends(get_session_store)],
) -> AuthToken:
    """Принимает email или телефон и пароль, возвращает подписанный JWT."""
    token = await login_user(session, credentials, settings, store)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return token
