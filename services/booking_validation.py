"""Бизнес-проверки бронирования.

Функции переиспользуются в POST и PATCH /booking. Сессия приходит параметром,
чтобы проверки работали в общей транзакции. Для PATCH передается
exclude_booking_id, иначе бронь будет конфликтовать сама с собой.

Правила изменения и отмены брони (реализуются в PATCH /booking/{id}, 11 пункт
в задаче):

1. Менять можно только свою бронь (USER), брони своих кафе (MANAGER) или любые
   (ADMIN).
2. Нельзя менять бронь, которая уже началась, а также со статусом ACTIVE или
   COMPLETED.
3. При смене даты, столов или слотов заново выполняются все проверки
   validate_booking_data с exclude_booking_id=<id брони>.
4. Старые строки booking_table_slots деактивируются (is_active=False), для
   новых пар создаются новые строки. Всё в одной транзакции.
5. Отмена: status=CANCELED и деактивация всех связанных активных строк
   booking_table_slots в той же транзакции. Иначе стол и слот останутся
   занятыми: индекс uq_table_slot_date смотрит только на is_active самой пары.
6. После смены даты пары нужно перечитать (session.refresh): в проекте
   expire_on_commit=False, а БД обновляет booking_date в парах сама
   (ON UPDATE CASCADE).
7. Напоминания старой брони деактивируются при изменении и отмене.
"""

from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from crud.base import CRUDBase
from crud.booking import booking_crud
from models import Cafe, Slot, Table
from schemas.booking import BookingTableSlot

from core.error_codes import ErrorCode
from core.exceptions import CustomException

_cafe_crud = CRUDBase(Cafe)
_table_crud = CRUDBase(Table)
_slot_crud = CRUDBase(Slot)


def get_today() -> date:
    """Возвращает текущую дату по UTC.

    Все проверки «не в прошлом» берут сегодняшнюю дату только отсюда.
    Так часовой пояс и источник даты задаются в одном месте: если проект
    решит считать дату по Москве, меняется эта функция, а не каждая проверка.
    Время в БД хранится в UTC (get_utc_now в core/base_model.py), поэтому
    и здесь UTC.
    """
    return datetime.now(timezone.utc).date()


def validate_booking_date(
    booking_date: date,
    today: date | None = None,
) -> None:
    """Проверяет, что дата брони не в прошлом (сегодня допустимо)."""
    if booking_date < (today or get_today()):
        raise CustomException(
            ErrorCode.BOOKING_DATE_IN_PAST,
            'Нельзя бронировать на прошедшую дату',
        )


def validate_guest_number(guest_number: int) -> None:
    """Проверяет, что количество гостей больше нуля."""
    if guest_number <= 0:
        raise CustomException(
            ErrorCode.INVALID_GUEST_NUMBER,
            'Количество гостей должно быть больше нуля',
        )


async def validate_cafe(session: AsyncSession, cafe_id: int) -> None:
    """Проверяет, что кафе существует и активно."""
    cafe = await _cafe_crud.get(session, cafe_id)
    if cafe is None or not cafe.is_active:
        raise CustomException(
            ErrorCode.CAFE_NOT_FOUND,
            f'Кафе {cafe_id} не найдено',
        )


async def load_tables_and_slots(
    session: AsyncSession,
    cafe_id: int,
    pairs: Sequence[BookingTableSlot],
) -> tuple[list[Table], list[Slot]]:
    """Загружает столы и слоты пар и проверяет их.

    Стол и слот должны существовать, быть активными и принадлежать кафе брони.
    Так как и стол, и слот принадлежат кафе брони, они тем самым принадлежат
    одному кафе.
    """
    table_ids = {p.table_id for p in pairs}
    slot_ids = {p.slot_id for p in pairs}
    tables = await _table_crud.get_by_ids(session, table_ids)
    slots = await _slot_crud.get_by_ids(session, slot_ids)

    missing_tables = table_ids - {t.id for t in tables}
    if missing_tables:
        raise CustomException(
            ErrorCode.TABLE_NOT_FOUND,
            f'Столы не найдены: {sorted(missing_tables)}',
        )
    missing_slots = slot_ids - {s.id for s in slots}
    if missing_slots:
        raise CustomException(
            ErrorCode.SLOT_NOT_FOUND,
            f'Слоты не найдены: {sorted(missing_slots)}',
        )

    for table in tables:
        if not table.is_active:
            raise CustomException(
                ErrorCode.TABLE_NOT_FOUND,
                f'Стол {table.id} не найден',
            )
        if table.cafe_id != cafe_id:
            raise CustomException(
                ErrorCode.TABLE_NOT_IN_CAFE,
                f'Стол {table.id} не принадлежит кафе {cafe_id}',
            )
    for slot in slots:
        if not slot.is_active:
            raise CustomException(
                ErrorCode.SLOT_NOT_FOUND,
                f'Слот {slot.id} не найден',
            )
        if slot.cafe_id != cafe_id:
            raise CustomException(
                ErrorCode.SLOT_NOT_IN_CAFE,
                f'Слот {slot.id} не принадлежит кафе {cafe_id}',
            )
    return tables, slots


def validate_capacity(tables: Sequence[Table], guest_number: int) -> None:
    """Проверяет, что сумма мест уникальных столов не меньше числа гостей."""
    total = sum(t.seat_number for t in {t.id: t for t in tables}.values())
    if total < guest_number:
        raise CustomException(
            ErrorCode.CAPACITY_EXCEEDED,
            f'Мест за выбранными столами {total}, а гостей {guest_number}',
        )


async def validate_tables_slots_free(
    session: AsyncSession,
    pairs: Sequence[BookingTableSlot],
    booking_date: date,
    exclude_booking_id: int | None = None,
) -> None:
    """Проверяет, что ни одна пара стол+слот не занята активной бронью на дату.

    Это предварительная проверка ради понятной ошибки. Окончательную защиту
    от гонки даёт частичный уникальный индекс uq_table_slot_date: его
    IntegrityError нужно превращать в TABLE_SLOT_OCCUPIED (задача POST).
    """
    occupied = await booking_crud.find_occupied_pairs(
        session,
        [(p.table_id, p.slot_id) for p in pairs],
        booking_date,
        exclude_booking_id,
    )
    if occupied:
        busy = sorted((o.table_id, o.slot_id) for o in occupied)
        raise CustomException(
            ErrorCode.TABLE_SLOT_OCCUPIED,
            f'Пары (стол, слот) уже заняты: {busy}',
        )


def slots_overlap(a: Slot, b: Slot) -> bool:
    """Возвращает True, если интервалы слотов пересекаются (касание ок)."""
    return a.start_time < b.end_time and b.start_time < a.end_time


async def validate_user_has_no_overlap(
    session: AsyncSession,
    user_id: int,
    booking_date: date,
    slots: Sequence[Slot],
    exclude_booking_id: int | None = None,
) -> None:
    """Проверка, что другие действующие брони юзера на дату не пересекаются."""
    others = await booking_crud.find_user_slots_on_date(
        session,
        user_id,
        booking_date,
        exclude_booking_id,
    )
    for new in slots:
        for other in others:
            if slots_overlap(new, other):
                raise CustomException(
                    ErrorCode.USER_BOOKING_OVERLAP,
                    'У пользователя уже есть бронь на пересекающееся время',
                )


async def validate_booking_data(
    session: AsyncSession,
    *,
    user_id: int,
    cafe_id: int,
    booking_date: date,
    guest_number: int,
    pairs: Sequence[BookingTableSlot],
    exclude_booking_id: int | None = None,
    today: date | None = None,
) -> None:
    """Выполняет полный набор проверок для POST и PATCH.

    Порядок: сначала дешёвые проверки без запросов, потом запросы к БД.
    """
    validate_booking_date(booking_date, today)
    validate_guest_number(guest_number)
    await validate_cafe(session, cafe_id)
    tables, slots = await load_tables_and_slots(session, cafe_id, pairs)
    validate_capacity(tables, guest_number)
    await validate_tables_slots_free(
        session,
        pairs,
        booking_date,
        exclude_booking_id,
    )
    await validate_user_has_no_overlap(
        session,
        user_id,
        booking_date,
        slots,
        exclude_booking_id,
    )
