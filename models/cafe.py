from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import UUID, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base_model import Base

if TYPE_CHECKING:
    from .action import ActionCafe
    from .booking import Booking
    from .dish import DishCafe
    from .media import Media
    from .slot import Slot
    from .table import Table
    from .user import User


class Cafe(Base):
    """Кафе с залом, слотами и меню.

    Поля:
        id: целочисленный идентификатор кафе.
        name: название кафе.
        address: адрес кафе.
        phone: контактный телефон кафе.
        description: необязательное описание кафе.
        photo_id: необязательная ссылка на запись Media.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('medias.id'),
    )

    photo: Mapped['Media | None'] = relationship()
    cafe_managers: Mapped[list['CafeManager']] = relationship(
        back_populates='cafe',
    )
    tables: Mapped[list['Table']] = relationship(
        back_populates='cafe',
    )
    slots: Mapped[list['Slot']] = relationship(
        back_populates='cafe',
    )
    bookings: Mapped[list['Booking']] = relationship(
        back_populates='cafe',
    )
    dish_cafes: Mapped[list['DishCafe']] = relationship(
        back_populates='cafe',
    )
    action_cafes: Mapped[list['ActionCafe']] = relationship(
        back_populates='cafe',
    )


class CafeManager(Base):
    """Связь пользователя с кафе в роли менеджера.

    Поля:
        id: идентификатор записи связи.
        cafe_id: идентификатор кафе.
        user_id: идентификатор пользователя-менеджера.
        is_active: признак действующей записи связи.
        created_at: время создания связи.
        updated_at: время последнего обновления связи.
    """

    __tablename__ = 'cafe_managers'

    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))

    cafe: Mapped[Cafe] = relationship(
        back_populates='cafe_managers',
    )
    user: Mapped['User'] = relationship(
        back_populates='cafe_managers',
    )

    __table_args__ = (
        UniqueConstraint(
            'cafe_id',
            'user_id',
            name='uq_cafe_managers',
        ),
    )
