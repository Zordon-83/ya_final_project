from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .enums import ReminderKind
from core.base_model import Base

if TYPE_CHECKING:
    from .booking import Booking


class Reminder(Base):
    """Напоминание о предстоящей брони.

    Поля:
        id: целочисленный идентификатор напоминания.
        booking_id: идентификатор связанной брони.
        kind: тип напоминания DAY или HOUR.
        remind_at: время, когда нужно отправить напоминание.
        sent_at: время отправки или NULL, если напоминание не отправлено.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    booking_id: Mapped[int] = mapped_column(ForeignKey('bookings.id'))
    kind: Mapped[ReminderKind] = mapped_column(
        Enum(ReminderKind, name='reminder_kind'),
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    booking: Mapped['Booking'] = relationship(
        back_populates='reminders',
    )

    __table_args__ = (
        Index(
            'uq_reminder_booking_kind',
            'booking_id',
            'kind',
            unique=True,
            postgresql_where=text('is_active'),
        ),
        Index(
            'ix_reminders_due',
            'remind_at',
            postgresql_where=text('sent_at IS NULL'),
        ),
    )
