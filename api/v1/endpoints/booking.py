"""Эндпоинты бронирований."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from models import User
from schemas.booking import BookingCreate, BookingInfo
from services.booking import create_booking

from core.db import get_session
from core.exceptions import CustomError

router = APIRouter(prefix='/booking')


@router.post(
    '',
    response_model=BookingInfo,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            'model': CustomError,
            'description': 'Нарушены бизнес-правила бронирования',
        },
        status.HTTP_401_UNAUTHORIZED: {
            'model': CustomError,
            'description': 'Требуется авторизация',
        },
    },
    status_code=status.HTTP_201_CREATED,
    summary='Создание нового бронирования',
)
async def create_booking_endpoint(
    data: BookingCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BookingInfo:
    """Создаёт бронь для текущего пользователя."""
    return await create_booking(session, current_user, data)
