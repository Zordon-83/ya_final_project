from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import main_router
from services.first_admin import ensure_first_admin

from core.db import session_maker
from core.exceptions import (
    CustomException,
    custom_exception_handler,
    http_exception_handler,
    server_exception_handler,
    validation_exception_handler,
)
from core.logging import log_event, log_exception, setup_logging
from core.logging_middleware import RequestLoggingMiddleware
from core.session_middleware import SessionRefreshMiddleware
from core.sessions import create_session_store
from core.settings import settings

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Открывает Redis, создаёт администратора и фиксирует жизненный цикл."""
    log_event('application_starting', 'application', 'started')
    store = None
    stopped_cleanly = False
    try:
        try:
            store = create_session_store()
            app.state.session_store = store
            if settings.first_admin_password is not None and settings.first_admin_lock_key is not None:
                async with session_maker.begin() as session:
                    created_id = await ensure_first_admin(
                        session,
                        email=settings.first_admin_email,
                        phone=settings.first_admin_phone,
                        password=settings.first_admin_password,
                        lock_key=settings.first_admin_lock_key,
                    )
                if created_id is not None:
                    log_event('created', 'user', 'success', entity_id=created_id)
        except Exception as error:
            log_exception('startup_failed', 'application', error)
            raise
        log_event('application_started', 'application', 'success')
        try:
            yield
        except Exception as error:
            log_exception('shutdown_failed', 'application', error)
            raise
        else:
            stopped_cleanly = True
    finally:
        if store is not None:
            try:
                await store.client.aclose()
            except Exception as error:
                log_exception('shutdown_failed', 'application', error)
                raise
            finally:
                if app.state.session_store is store:
                    app.state.session_store = None
        if stopped_cleanly:
            log_event('application_stopped', 'application', 'success')


app = FastAPI(
    lifespan=lifespan,
    title=settings.title,
    version=settings.version,
    description=settings.description,
)


app.include_router(main_router)
app.add_middleware(SessionRefreshMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.get(
    path='/',
    response_model=dict,
)
async def index() -> dict:
    """Основная страница."""
    return {
        'app': f'{settings.title} ({settings.version})',
        'description': settings.description,
        'status': 'OK',
    }


app.add_exception_handler(CustomException, custom_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, server_exception_handler)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, log_config=None)
