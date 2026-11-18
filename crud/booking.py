from collections.abc import Collection
from datetime import date

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from crud.base import CRUDBase
from models import Booking, BookingTableSlot, Slot
from models.enums import BookingStatus


class CRUDBooking(CRUDBase[Booking]):
    """CRUD броней и запросы для проверок бронирования."""

    async def find_occupied_pairs(
        self,
        session: AsyncSession,
        pairs: Collection[tuple[int, int]],
        booking_date: date,
        exclude_booking_id: int | None = None,
    ) -> list[BookingTableSlot]:
        """Активные пары (стол, слот) на дату.

        Повторяет условие индекса uq_table_slot_date. exclude_booking_id нужен
        для PATCH, чтобы бронь не конфликтовала сама с собой.
        """
        if not pairs:
            return []
        stmt = select(BookingTableSlot).where(
            BookingTableSlot.is_active.is_(True),
            BookingTableSlot.booking_date == booking_date,
            tuple_(
                BookingTableSlot.table_id,
                BookingTableSlot.slot_id,
            ).in_(list(pairs)),
        )
        if exclude_booking_id is not None:
            stmt = stmt.where(
                BookingTableSlot.booking_id != exclude_booking_id,
            )
        return list(await session.scalars(stmt))

    async def find_user_slots_on_date(
        self,
        session: AsyncSession,
        user_id: int,
        booking_date: date,
        exclude_booking_id: int | None = None,
    ) -> list[Slot]:
        """Слоты действующих броней пользователя на дату (во всех кафе)."""
        stmt = (
            select(Slot)
            .join(BookingTableSlot, BookingTableSlot.slot_id == Slot.id)
            .join(Booking, Booking.id == BookingTableSlot.booking_id)
            .where(
                Booking.user_id == user_id,
                Booking.booking_date == booking_date,
                Booking.is_active.is_(True),
                Booking.status != BookingStatus.CANCELED,
                BookingTableSlot.is_active.is_(True),
            )
        )
        if exclude_booking_id is not None:
            stmt = stmt.where(Booking.id != exclude_booking_id)
        return list(await session.scalars(stmt))

    async def get_with_relations(
        self,
        session: AsyncSession,
        booking_id: int,
    ) -> Booking | None:
        """Бронь вместе с пользователем, кафе, парами, столами и слотами."""
        stmt = (
            select(Booking)
            .where(Booking.id == booking_id)
            .options(
                selectinload(Booking.user),
                selectinload(Booking.cafe),
                selectinload(Booking.table_slots).selectinload(
                    BookingTableSlot.table,
                ),
                selectinload(Booking.table_slots).selectinload(
                    BookingTableSlot.slot,
                ),
            )
            .execution_options(populate_existing=True)
        )
        return await session.scalar(stmt)


booking_crud = CRUDBooking(Booking)
