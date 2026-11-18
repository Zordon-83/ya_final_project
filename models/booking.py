from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .enums import BookingStatus
from core.base_model import Base

if TYPE_CHECKING:
    from .cafe import Cafe
    from .reminder import Reminder
    from .slot import Slot
    from .table import Table
    from .user import User


class Booking(Base):
    """Бронь пользователя в кафе.

    Поля:
        id: целочисленный идентификатор брони.
        user_id: идентификатор пользователя, создавшего бронь.
        cafe_id: идентификатор кафе.
        booking_date: дата бронирования.
        guest_number: количество гостей.
        status: состояние брони.
        note: необязательный комментарий пользователя.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))
    booking_date: Mapped[date] = mapped_column(Date)
    guest_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name='booking_status'),
        default=BookingStatus.BOOKING,
        server_default=BookingStatus.BOOKING.value,
    )
    note: Mapped[str | None] = mapped_column(Text)

    user: Mapped['User'] = relationship(
        back_populates='bookings',
    )
    cafe: Mapped['Cafe'] = relationship(
        back_populates='bookings',
    )
    table_slots: Mapped[list['BookingTableSlot']] = relationship(
        back_populates='booking',
    )
    reminders: Mapped[list['Reminder']] = relationship(
        back_populates='booking',
    )

    __table_args__ = (
        CheckConstraint(
            'guest_number > 0',
            name='ck_bookings_guest_number',
        ),
        UniqueConstraint(
            'id',
            'booking_date',
            name='uq_bookings_id_date',
        ),
        Index('ix_bookings_user_id', 'user_id'),
        Index('ix_bookings_cafe_id', 'cafe_id'),
    )


class BookingTableSlot(Base):
    """Забронированная пара «стол + временной слот».

    Поля:
        id: идентификатор записи связи.
        booking_id: идентификатор брони.
        booking_date: копия даты брони для составного внешнего ключа.
        table_id: идентификатор выбранного стола.
        slot_id: идентификатор выбранного временного слота.
        is_active: признак действующей записи связи.
        created_at: время создания связи.
        updated_at: время последнего обновления связи.
    """

    __tablename__ = 'booking_table_slots'

    booking_id: Mapped[int] = mapped_column(Integer)
    booking_date: Mapped[date] = mapped_column(Date)
    table_id: Mapped[int] = mapped_column(ForeignKey('tables.id'))
    slot_id: Mapped[int] = mapped_column(ForeignKey('slots.id'))

    booking: Mapped[Booking] = relationship(
        back_populates='table_slots',
    )
    table: Mapped['Table'] = relationship(
        back_populates='booking_table_slots',
    )
    slot: Mapped['Slot'] = relationship(
        back_populates='booking_table_slots',
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ['booking_id', 'booking_date'],
            ['bookings.id', 'bookings.booking_date'],
            name='fk_booking_table_slots_booking',
            onupdate='CASCADE',
        ),
        Index(
            'uq_table_slot_date',
            'table_id',
            'slot_id',
            'booking_date',
            unique=True,
            postgresql_where=text('is_active'),
        ),
        Index('ix_booking_table_slots_booking_id', 'booking_id'),
    )
