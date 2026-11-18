from typing import AsyncIterator

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.audit import commit_with_audit
from core.exceptions import CustomException
from core.logging import log_exception
from core.settings import settings

async_engine = create_async_engine(
    url=settings.db_url,
    pool_pre_ping=True,
)

session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Получение асинхронной сессии для FastAPI Depends."""
    async with session_maker() as session:
        try:
            yield session  # noqa: ASYNC119
            await commit_with_audit(session)
        except SQLAlchemyError as error:
            await session.rollback()
            log_exception('server_error', 'http', error)
            raise CustomException(
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message='Ошибка при работе с БД',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            session.info.pop('audit_events', None)
            await session.close()
