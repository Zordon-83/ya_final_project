from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base_model import Base

if TYPE_CHECKING:
    from .cafe import Cafe
    from .media import Media


class Dish(Base):
    """Блюдо меню кафе.

    Поля:
        id: целочисленный идентификатор блюда.
        name: название блюда.
        description: необязательное описание блюда.
        price: цена блюда с точностью до двух знаков.
        photo_id: необязательная ссылка на запись Media.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    __tablename__ = 'dishes'

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('medias.id'),
    )

    photo: Mapped['Media | None'] = relationship()
    dish_cafes: Mapped[list['DishCafe']] = relationship(
        back_populates='dish',
    )
    cafes: Mapped[list['Cafe']] = relationship(
        secondary='dish_cafes',
        primaryjoin='Dish.id == DishCafe.dish_id',
        secondaryjoin=('(Cafe.id == DishCafe.cafe_id) & DishCafe.is_active.is_(True)'),
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            'price >= 0',
            name='ck_dishes_price',
        ),
    )


class DishCafe(Base):
    """Связь блюда с кафе.

    Поля:
        id: идентификатор записи связи.
        dish_id: идентификатор блюда.
        cafe_id: идентификатор кафе.
        is_active: признак действующей записи связи.
        created_at: время создания связи.
        updated_at: время последнего обновления связи.
    """

    __tablename__ = 'dish_cafes'

    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id'))
    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))

    dish: Mapped[Dish] = relationship(
        back_populates='dish_cafes',
    )
    cafe: Mapped['Cafe'] = relationship(
        back_populates='dish_cafes',
    )

    __table_args__ = (
        UniqueConstraint(
            'dish_id',
            'cafe_id',
            name='uq_dish_cafes',
        ),
    )
