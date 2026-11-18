from fastapi import APIRouter

from .constants import PREFIX_API
from .v1.endpoints import auth_router, booking_router, health_router, users_router

main_router = APIRouter(prefix=f'/{PREFIX_API}/v1')

main_router.include_router(booking_router, tags=['Бронирования'])
main_router.include_router(health_router, tags=['System'])

main_router.include_router(auth_router, tags=['Аутентификация'])
main_router.include_router(users_router, tags=['Пользователи'])
