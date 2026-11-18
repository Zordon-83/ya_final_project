from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.auth_errors import unauthorized
from core.exceptions import CustomException, custom_exception_handler


class SessionRefreshMiddleware(BaseHTTPMiddleware):
    """Обновляет окно бездействия только после успешной обработки закрытого запроса."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Ошибки 4xx/5xx и публичные ручки не продлевают сессию."""
        response = await call_next(request)
        context = getattr(request.state, 'auth_session', None)
        if (
            context is not None
            and status.HTTP_200_OK <= response.status_code < status.HTTP_300_MULTIPLE_CHOICES
        ):
            store, jti, user_id, expires_at = context
            try:
                if not await store.refresh(jti, user_id, expires_at):
                    raise unauthorized()
            except CustomException as error:
                return await custom_exception_handler(request, error)
        return response
