import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logging import actor_context, log_event, log_exception


class CustomError(BaseModel):
    """Единое тело ошибки для обработчиков исключений и документации OpenAPI."""

    code: int
    message: str


class CustomException(Exception):
    """Базовый класс для пользовательских ошибок."""

    def __init__(self, code: int, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        """Инициализация пользовательской бизнес-ошибки."""
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


async def custom_exception_handler(request: Request, exc: CustomException) -> JSONResponse:
    """Обработчик кастомных ошибок."""
    log_event(
        'access_denied' if exc.status_code in (401, 403) else 'business_rejected',
        'http',
        'denied' if exc.status_code in (401, 403) else 'failure',
        status_code=exc.status_code,
        level=logging.ERROR if exc.status_code >= 500 else logging.WARNING,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=CustomError(code=exc.code, message=exc.message).model_dump(),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Обработчик ошибок валидации входящих данных (неверные данные)."""
    log_event('validation_failed', 'http', 'failure', status_code=422, level=logging.WARNING)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=CustomError(
            code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message='Ошибка валидации данных',
        ).model_dump(),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Обработчик встроенных HTTP-ошибок FastAPI."""
    log_event(
        'access_denied' if exc.status_code in (401, 403) else 'http_rejected',
        'http',
        'denied' if exc.status_code in (401, 403) else 'failure',
        status_code=exc.status_code,
        level=logging.ERROR if exc.status_code >= 500 else logging.WARNING,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=CustomError(code=exc.status_code, message=str(exc.detail)).model_dump(),
    )


async def server_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Не раскрывает причину 500 и использует общий контракт ошибок."""
    with actor_context(request.scope.get('audit_actor')):
        log_exception('server_error', 'http', exc)
    return JSONResponse({'code': 500, 'message': 'Внутренняя ошибка сервера'}, status_code=500)
