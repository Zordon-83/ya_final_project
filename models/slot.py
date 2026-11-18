from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base_model import Base

if TYPE_CHECKING:
    from .booking import BookingTableSlot
    from .cafe import Cafe


class Slot(Base):
    """Временной слот бронирования в кафе.

    Поля:
        id: целочисленный идентификатор слота.
        cafe_id: идентификатор кафе-владельца.
        start_time: время начала интервала.
        end_time: время окончания интервала.
        description: необязательное описание интервала.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    description: Mapped[str | None] = mapped_column(Text)

    cafe: Mapped['Cafe'] = relationship(
        back_populates='slots',
    )
    booking_table_slots: Mapped[list['BookingTableSlot']] = relationship(
        back_populates='slot',
    )

    __table_args__ = (
        Index(
            'uq_cafe_id_start_time_end_time',
            'cafe_id',
            'start_time',
            'end_time',
            unique=True,
            postgresql_where=text('is_active'),
        ),
        CheckConstraint(
            'start_time < end_time',
            name='ck_slots_time',
        ),
        Index('ix_slots_cafe_id', 'cafe_id'),
    )
