"""Создание и перенос reminders в транзакции сервиса бронирования, без commit."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.booking import Booking, BookingTableSlot
from models.enums import BookingStatus, ReminderKind
from models.reminder import Reminder
from models.slot import Slot

from core.exceptions import CustomException
from core.settings import Settings, settings

MOSCOW = ZoneInfo('Europe/Moscow')


def _utc_now(value: datetime | None) -> datetime:
    """Принимает только aware-часы; один снимок времени на всю операцию."""
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('now должен содержать часовой пояс')
    return value.astimezone(UTC)


async def _lock_booking(session: AsyncSession, booking_id: int) -> Booking:
    """Публикует изменения вызывающей стороны в БД и сериализует операции одной брони."""
    if type(booking_id) is not int or not 0 < booking_id < 2**31:
        raise ValueError('booking_id должен быть положительным PostgreSQL INTEGER')
    await session.flush()
    booking = await session.scalar(
        select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    if booking is None:
        raise CustomException(404, 'Бронирование не найдено', status_code=404)
    return booking


def _scheduled(booking: Booking) -> bool:
    """Отменённая, текущая или завершённая бронь не получает новые reminders."""
    return booking.is_active and booking.status == BookingStatus.BOOKING


async def _booking_start(session: AsyncSession, booking: Booking) -> datetime:
    """Читает текущие связи без lazy loading и без устаревшего relationship-кэша."""
    rows = (
        await session.execute(
            select(
                BookingTableSlot.booking_date,
                Slot.id,
                Slot.cafe_id,
                Slot.is_active,
                Slot.start_time,
                Slot.end_time,
            )
            .select_from(BookingTableSlot)
            .outerjoin(Slot, Slot.id == BookingTableSlot.slot_id)
            .where(BookingTableSlot.booking_id == booking.id, BookingTableSlot.is_active.is_(True)),
        )
    ).all()
    if not rows:
        raise CustomException(400, 'У бронирования нет активных временных слотов')
    starts = []
    for booking_date, slot_id, cafe_id, active, start, end in rows:
        if slot_id is None or not active:
            raise CustomException(404, 'Временной слот бронирования не найден', status_code=404)
        if cafe_id != booking.cafe_id or booking_date != booking.booking_date:
            raise CustomException(400, 'Временной слот не соответствует кафе или дате бронирования')
        if start.tzinfo is not None or end.tzinfo is not None or start >= end:
            raise CustomException(400, 'Некорректный временной интервал бронирования')
        starts.append(start)
    return datetime.combine(booking.booking_date, min(starts), tzinfo=MOSCOW).astimezone(UTC)


def _plan(start: datetime, now: datetime, config: Settings) -> dict[ReminderKind, datetime]:
    """DAY задаётся в днях, HOUR — в часах; прошедшие моменты исключаются."""
    try:
        offsets = {
            ReminderKind.DAY: timedelta(days=config.reminder_day_days),
            ReminderKind.HOUR: timedelta(hours=config.reminder_hour_hours),
        }
    except OverflowError:
        raise ValueError('Интервал напоминания слишком велик') from None
    planned = {}
    for kind, offset in offsets.items():
        if offset <= timedelta(0):
            raise ValueError('Интервал напоминания должен быть положительным')
        try:
            remind_at = start - offset
        except OverflowError:
            continue  # Момент раньше минимального datetime заведомо уже прошёл.
        if remind_at >= now:
            planned[kind] = remind_at
    return planned


async def _active_reminders(session: AsyncSession, booking_id: int) -> list[Reminder]:
    """Загружает только актуальные строки одной брони, включая уже отправленные."""
    return list(
        await session.scalars(
            select(Reminder)
            .where(Reminder.booking_id == booking_id, Reminder.is_active.is_(True))
            .order_by(Reminder.id)
            .execution_options(populate_existing=True),
        ),
    )


async def _insert(
    session: AsyncSession,
    booking_id: int,
    plan: dict[ReminderKind, datetime],
    existing: set[ReminderKind],
) -> list[Reminder]:
    """Создаёт только отсутствующие kinds; уже отправленный active-kind не дублируется."""
    created = [
        Reminder(booking_id=booking_id, kind=kind, remind_at=remind_at, sent_at=None, is_active=True)
        for kind, remind_at in plan.items()
        if kind not in existing
    ]
    if created:
        session.add_all(created)
        await session.flush()
    return created


async def create_reminders(
    session: AsyncSession,
    booking_id: int,
    *,
    now: datetime | None = None,
    config: Settings | None = None,
) -> list[Reminder]:
    """Возвращает новые строки; повторный вызов не изменяет существующие reminders."""
    clock = _utc_now(now) if now is not None else None
    booking = await _lock_booking(session, booking_id)
    if not _scheduled(booking):
        return []
    clock = clock if clock is not None else _utc_now(None)
    plan = _plan(await _booking_start(session, booking), clock, config if config is not None else settings)
    if not plan:
        return []
    active = await _active_reminders(session, booking_id)
    return await _insert(session, booking_id, plan, {row.kind for row in active})


def _stored_utc(value: datetime) -> datetime:
    """SQLite теряет tzinfo у TIMESTAMP WITH TIME ZONE; хранимый контракт — UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def reschedule_reminders(
    session: AsyncSession,
    booking_id: int,
    *,
    now: datetime | None = None,
    config: Settings | None = None,
) -> list[Reminder]:
    """Заменяет устаревшие моменты; неизменившиеся строки сохраняются без повторной отправки."""
    clock = _utc_now(now) if now is not None else None
    booking = await _lock_booking(session, booking_id)
    clock = clock if clock is not None else _utc_now(None)
    plan = (
        _plan(await _booking_start(session, booking), clock, config if config is not None else settings)
        if _scheduled(booking)
        else {}
    )
    active = await _active_reminders(session, booking_id)
    unchanged = set()
    changed = False
    for row in active:
        if row.kind in plan and _stored_utc(row.remind_at) == plan[row.kind]:
            unchanged.add(row.kind)
        else:
            row.is_active = False
            changed = True
    if changed:
        await session.flush()  # Освобождает partial unique index ДО INSERT новых kinds.
    return await _insert(session, booking_id, plan, unchanged)


async def deactivate_reminders(session: AsyncSession, booking_id: int) -> int:
    """Деактивирует строки без удаления и без изменения sent_at; возвращает их количество."""
    await _lock_booking(session, booking_id)
    active = await _active_reminders(session, booking_id)
    for row in active:
        row.is_active = False
    if active:
        await session.flush()
    return len(active)
