"""ASGI-контекст запроса без захвата заголовков, URL и тела."""

import logging
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from core.logging import actor_context, log_event, log_exception

ASGIApp = Callable[..., Awaitable[None]]


class RequestLoggingMiddleware:
    """Один изменяемый actor на запрос, включая дочерние задачи BaseHTTPMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        """Сохраняет следующее ASGI-приложение."""
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: ASGIApp,
        send: ASGIApp,
    ) -> None:
        """Логирует завершение запроса и сбрасывает контекст даже при исключении."""
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        actor = {'actor': 'ANONYMOUS', 'user_id': None, 'username': None}
        scope['audit_actor'] = actor
        status_code = 500

        async def capture_status(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
            await send(message)

        with actor_context(actor):
            log_event('http_request', 'http', 'started', level=logging.DEBUG)
            try:
                await self.app(scope, receive, capture_status)
            except Exception as error:
                log_exception('server_error', 'http', error)
                raise
            else:
                log_event(
                    'http_request',
                    'http',
                    'success' if status_code < 400 else 'failure',
                    status_code=status_code,
                    level=logging.ERROR
                    if status_code >= 500
                    else (logging.WARNING if status_code >= 400 else logging.INFO),
                )
