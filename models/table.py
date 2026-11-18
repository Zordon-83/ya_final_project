from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base_model import Base

if TYPE_CHECKING:
    from .booking import BookingTableSlot
    from .cafe import Cafe


class Table(Base):
    """Стол кафе и его вместимость.

    Поля:
        id: целочисленный идентификатор стола.
        cafe_id: идентификатор кафе-владельца.
        seat_number: количество мест за столом.
        description: необязательное описание стола.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))
    seat_number: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    cafe: Mapped['Cafe'] = relationship(
        back_populates='tables',
    )
    booking_table_slots: Mapped[list['BookingTableSlot']] = relationship(
        back_populates='table',
    )

    __table_args__ = (
        CheckConstraint(
            'seat_number > 0',
            name='ck_tables_seat_number',
        ),
        Index('ix_tables_cafe_id', 'cafe_id'),
    )
