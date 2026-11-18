from asyncio import to_thread
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from pwdlib import PasswordHash
from pydantic import SecretStr
from sqlalchemy import BigInteger, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Booking, BookingTableSlot, Cafe, CafeManager, Slot, Table, User
from models.enums import BookingStatus, UserRole
from schemas.user import UserCreate

from core.base_model import Base
from core.phone import normalize_phone

DEMO_PASSWORD = 'CafeDemo-2026!'
PREFIX = 'usr07:v1'
SEED_LOCK = 735_007_2026
USER_NAMES = ('admin', 'manager1', 'manager2', 'user1', 'user2', 'user3', 'phone')
SLOT_HOURS = ((10, 12), (13, 15), (16, 18))
# Пользователь, кафе, стол, слот, смещение дня, число гостей (индексы от нуля).
BOOKING_PLAN = ((3, 0, 0, 0, 0, 2), (4, 1, 1, 1, 1, 3), (5, 2, 2, 2, 2, 4), (6, 0, 1, 1, 1, 2))
BOOKING_NOTES = tuple(f'{PREFIX}:booking:{index}' for index in range(1, 5))
password_hasher = PasswordHash.recommended()


class DemoSeedError(Exception):
    """Конфликт демо-набора, при котором вся транзакция должна быть отменена."""


def demo_today() -> date:
    """Определяет день учебного стенда по Москве (UTC+3)."""
    return datetime.now(timezone(timedelta(hours=3))).date()


class SeedWriter:
    """Добавляет недостающие записи и проверяет неизменяемые признаки уже имеющихся."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет общую транзакцию и счётчики без персональных секретов."""
        self.session = session
        self.created: Counter[str] = Counter()
        self.existing: Counter[str] = Counter()

    async def ensure(
        self,
        model: type[Base],
        key: dict,
        values: dict,
        create_only: dict | None = None,
    ) -> Any:
        """Не изменяет существующие записи; несовместимое совпадение останавливает запуск."""
        records = (await self.session.scalars(select(model).filter_by(**key))).all()
        if len(records) > 1:
            raise DemoSeedError(f'Неоднозначный демо-ключ в {model.__tablename__}')
        if records:
            record = records[0]
            if any(getattr(record, field) != value for field, value in values.items()):
                raise DemoSeedError(f'Демо-запись изменена или конфликтует в {model.__tablename__}')
            self.existing[model.__tablename__] += 1
            return record
        record = model(**(key | values | (create_only or {})))
        self.session.add(record)
        await self.session.flush()
        self.created[model.__tablename__] += 1
        return record


async def seed_users(writer: SeedWriter) -> list[User]:
    """Создаёт семь аккаунтов, не перехватывая занятые контакты и не сбрасывая пароли."""
    users = []
    roles = (UserRole.ADMIN, UserRole.MANAGER, UserRole.MANAGER) + (UserRole.USER,) * 4
    for index, (name, role) in enumerate(zip(USER_NAMES, roles, strict=True), start=1):
        data = UserCreate(
            username=f'demo_{name}',
            email=f'demo.{name}@example.com' if name != 'phone' else None,
            phone=f'+1202555010{index}',
            password=SecretStr(DEMO_PASSWORD),
        )
        email = str(data.email) if data.email is not None else None
        candidates = (
            await writer.session.scalars(
                select(User).where(
                    or_(
                        User.username == data.username,
                        User.phone == data.phone,
                        func.lower(User.email) == email if email is not None else False,
                    ),
                ),
            )
        ).all()
        if candidates and (len(candidates) != 1 or candidates[0].username != data.username):
            raise DemoSeedError('Имя или контакт демо-пользователя уже заняты')
        create_only = {}
        if not candidates:
            create_only['password_hash'] = await to_thread(
                password_hasher.hash,
                data.password.get_secret_value(),
            )
        users.append(
            await writer.ensure(
                User,
                {'username': data.username},
                {'email': email, 'phone': data.phone, 'role': role},
                create_only,
            ),
        )
    return users


async def seed_cafes(
    writer: SeedWriter,
    users: list[User],
) -> tuple[list[Cafe], list[list[Table]], list[list[Slot]]]:
    """Создаёт три кафе с менеджерами, девять столов и девять непересекающихся слотов."""
    cafes, tables, slots = [], [], []
    for number, label in enumerate(('Утро', 'День', 'Вечер'), start=1):
        name = f'[DEMO USR-07] {label}'
        marker = f'{PREFIX}:cafe:{number}'
        conflict = await writer.session.scalar(
            select(Cafe.id).where(
                Cafe.name == name,
                or_(Cafe.description != marker, Cafe.description.is_(None)),
            ),
        )
        if conflict is not None:
            raise DemoSeedError('Название демо-кафе уже занято')
        cafe = await writer.ensure(
            Cafe,
            {'description': marker},
            {
                'name': name,
                'address': f'Демо-улица, {number}',
                'phone': normalize_phone(f'+1202555012{number}'),
            },
        )
        cafes.append(cafe)
        manager = users[1 if number in (1, 3) else 2]
        await writer.ensure(CafeManager, {'cafe_id': cafe.id, 'user_id': manager.id}, {})
        cafe_tables = []
        cafe_slots = []
        for index, seats in enumerate((2, 4, 6), start=1):
            cafe_tables.append(
                await writer.ensure(
                    Table,
                    {'description': f'{PREFIX}:table:{number}:{index}'},
                    {'cafe_id': cafe.id, 'seat_number': seats},
                ),
            )
        for index, (start, end) in enumerate(SLOT_HOURS, start=1):
            slot_marker = f'{PREFIX}:slot:{number}:{index}'
            overlap = await writer.session.scalar(
                select(Slot.id).where(
                    Slot.cafe_id == cafe.id,
                    Slot.is_active.is_(True),
                    or_(Slot.description != slot_marker, Slot.description.is_(None)),
                    Slot.start_time < time(end),
                    Slot.end_time > time(start),
                ),
            )
            if overlap is not None:
                raise DemoSeedError('В демо-кафе есть пересекающийся временной слот')
            cafe_slots.append(
                await writer.ensure(
                    Slot,
                    {'description': slot_marker},
                    {'cafe_id': cafe.id, 'start_time': time(start), 'end_time': time(end)},
                ),
            )
        tables.append(cafe_tables)
        slots.append(cafe_slots)
    return cafes, tables, slots


async def booking_start(session: AsyncSession, requested: date | None, today: date) -> date:
    """Сохраняет дату первого запуска, чтобы повторы в другие дни не порождали новые брони."""
    existing = (await session.scalars(select(Booking).where(Booking.note.in_(BOOKING_NOTES)))).all()
    anchors = {
        booking.booking_date - timedelta(days=BOOKING_PLAN[BOOKING_NOTES.index(booking.note)][4])
        for booking in existing
    }
    if len(anchors) > 1:
        raise DemoSeedError('Даты демо-броней изменены: автоматическое перемещение запрещено')
    if anchors:
        anchor = anchors.pop()
        if requested is not None and requested != anchor:
            raise DemoSeedError('Демо-брони уже созданы на другую дату; их даты не изменяются')
        return anchor
    start = requested or today + timedelta(days=1)
    if start < today + timedelta(days=1):
        raise DemoSeedError('Первая дата демо-броней должна быть не раньше завтрашнего дня')
    if start > date.max - timedelta(days=2):
        raise DemoSeedError('Дата не оставляет места для трёх дней бронирования')
    return start


async def seed_bookings(
    writer: SeedWriter,
    users: list[User],
    cafes: list[Cafe],
    tables: list[list[Table]],
    slots: list[list[Slot]],
    start: date,
    today: date,
) -> None:
    """Создаёт четыре брони со связями в одном кафе и достаточной вместимостью стола."""
    for note, (user, cafe, table, slot, offset, guests) in zip(BOOKING_NOTES, BOOKING_PLAN, strict=True):
        day = start + timedelta(days=offset)
        if (
            day < today
            and await writer.session.scalar(select(Booking.id).where(Booking.note == note)) is None
        ):
            raise DemoSeedError('Нельзя восстанавливать недостающую демо-бронь в прошлом')
        booking = await writer.ensure(
            Booking,
            {'note': note},
            {
                'user_id': users[user].id,
                'cafe_id': cafes[cafe].id,
                'booking_date': day,
                'guest_number': guests,
            },
        )
        await writer.ensure(
            BookingTableSlot,
            {'booking_id': booking.id},
            {'booking_date': day, 'table_id': tables[cafe][table].id, 'slot_id': slots[cafe][slot].id},
            {
                'is_active': booking.is_active
                and booking.status in (BookingStatus.BOOKING, BookingStatus.ACTIVE),
            },
        )


async def seed_demo(session: AsyncSession, start_date: date | None = None) -> dict:
    """Заполняет демо-набор внутри транзакции вызывающей стороны, без commit и внешних отправок."""
    await session.execute(select(func.pg_advisory_xact_lock(cast(SEED_LOCK, BigInteger))))
    today = demo_today()
    start = await booking_start(session, start_date, today)
    writer = SeedWriter(session)
    users = await seed_users(writer)
    cafes, tables, slots = await seed_cafes(writer, users)
    await seed_bookings(writer, users, cafes, tables, slots, start, today)
    return {
        'created': dict(writer.created),
        'existing': dict(writer.existing),
        'booking_start': start.isoformat(),
    }
