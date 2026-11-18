from fastapi import status

from core.exceptions import CustomException


def unauthorized() -> CustomException:
    """Возвращает одинаковую ошибку для всех недействительных учётных данных."""
    return CustomException(
        code=status.HTTP_401_UNAUTHORIZED,
        message='Требуется авторизация',
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


def auth_unavailable() -> CustomException:
    """Не раскрывает настройки или текст ошибки Redis клиенту."""
    return CustomException(
        code=status.HTTP_503_SERVICE_UNAVAILABLE,
        message='Авторизация временно недоступна',
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
