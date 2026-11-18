"""Базовый CRUD. Транзакцией управляет get_session, поэтому здесь flush."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CRUDBase[ModelT]:
    """Общие операции над моделью. Удаления нет: оиспользуем is_active."""

    def __init__(self, model: type[ModelT]) -> None:
        """Сохраняет модель, с которой работает CRUD."""
        self.model = model

    async def get(self, session: AsyncSession, obj_id: Any) -> ModelT | None:
        """Объект по id или None."""
        return await session.get(self.model, obj_id)

    async def get_by_ids(self, session: AsyncSession, ids: Collection[Any]) -> list[ModelT]:
        """Объекты по списку id. Отсутствующие id в результат не попадают."""
        if not ids:
            return []
        result = await session.scalars(select(self.model).where(self.model.id.in_(ids)))
        return list(result)

    async def get_multi(self, session: AsyncSession, *, show_active: bool | None = None) -> list[ModelT]:
        """Все объекты; show_active=True/False => только активные/нет."""
        stmt = select(self.model).order_by(self.model.id)
        if show_active is not None:
            stmt = stmt.where(self.model.is_active.is_(show_active))
        return list(await session.scalars(stmt))

    async def create(self, session: AsyncSession, data: Mapping[str, Any]) -> ModelT:
        """Создаёт объект и делает flush, чтобы получить id."""
        obj = self.model(**data)
        session.add(obj)
        await session.flush()
        return obj

    async def update(self, session: AsyncSession, obj: ModelT, data: Mapping[str, Any]) -> ModelT:
        """Меняет переданные поля и делает flush. Коммит не выполняется."""
        for field, value in data.items():
            setattr(obj, field, value)
        await session.flush()
        return obj

    async def delete(self, session: AsyncSession, obj: ModelT) -> ModelT:
        """Мягкое удаление: ставит is_active=False, саму запись не удаляет."""
        obj.is_active = False
        await session.flush()
        return obj
