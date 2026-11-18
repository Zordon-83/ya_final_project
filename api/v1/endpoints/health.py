from fastapi import APIRouter

router = APIRouter()


@router.get('/health', summary='Проверка доступности сервиса')
async def check_health() -> dict:
    """Эндпоинт для проверки статуса приложения."""
    return {'status': 'OK'}
