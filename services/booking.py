"""Бизнес-операции с бронями."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from crud.booking import booking_crud
from models import Booking, BookingTableSlot, User
from schemas.booking import BookingCreate
from services.booking_notifications import on_booking_created
from services.booking_validation import validate_booking_data

from core.error_codes import ErrorCode
from core.exceptions import CustomException

ACTIVE_SLOT_INDEX = 'uq_table_slot_date'


async def create_booking(
    session: AsyncSession,
    user: User,
    data: BookingCreate,
) -> Booking:
    """Создаёт бронь и пары стол + слот одной транзакцией."""
    await validate_booking_data(
        session,
        user_id=user.id,
        cafe_id=data.cafe_id,
        booking_date=data.booking_date,
        guest_number=data.guest_number,
        pairs=data.tables_slots,
    )

    try:
        async with session.begin_nested():
            booking = await booking_crud.create(
                session,
                {
                    'user_id': user.id,
                    'cafe_id': data.cafe_id,
                    'booking_date': data.booking_date,
                    'guest_number': data.guest_number,
                    'note': data.note,
                },
            )
            session.add_all(
                BookingTableSlot(
                    booking_id=booking.id,
                    booking_date=booking.booking_date,
                    table_id=pair.table_id,
                    slot_id=pair.slot_id,
                )
                for pair in data.tables_slots
            )
            await session.flush()
    except IntegrityError as exc:
        if ACTIVE_SLOT_INDEX in str(exc.orig):
            raise CustomException(
                ErrorCode.TABLE_SLOT_OCCUPIED,
                'Стол и слот на эту дату уже заняты другой бронью',
            ) from exc
        raise

    booking = await booking_crud.get_with_relations(session, booking.id)
    await session.commit()
    await on_booking_created(booking.id)
    return booking
