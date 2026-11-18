import uuid
from datetime import date, datetime, time

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from models.enums import BookingStatus
from schemas.user import UserShortInfo


def _check_unique_pairs(pairs: list['BookingTableSlot']) -> None:
    keys = [(p.table_id, p.slot_id) for p in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('Пары стол + слот не должны повторяться')


class CafeShortInfo(BaseModel):
    """Краткая информация о кафе."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    phone: str
    description: str | None = None
    photo_id: uuid.UUID | None = None


class TableShortInfo(BaseModel):
    """Краткая информация о столе."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str | None = None
    seat_number: int


class TimeSlotShortInfo(BaseModel):
    """Краткая информация о временном слоте."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    start_time: time
    end_time: time
    description: str | None = None


class BookingTableSlot(BaseModel):
    """Пара «стол + слот» в запросе."""

    table_id: int = Field(gt=0)
    slot_id: int = Field(gt=0)


class BookingTableSlotShortInfo(BaseModel):
    """Пара «стол + слот» в ответе."""

    model_config = ConfigDict(from_attributes=True)

    table: TableShortInfo
    slot: TimeSlotShortInfo


class BookingCreate(BaseModel):
    """Данные для создания брони."""

    cafe_id: int = Field(gt=0)
    tables_slots: list[BookingTableSlot] = Field(min_length=1)
    guest_number: int = Field(gt=0)
    note: str | None = None
    booking_date: date

    @field_validator('tables_slots')
    @classmethod
    def unique_pairs(
        cls,
        value: list[BookingTableSlot],
    ) -> list[BookingTableSlot]:
        """Пары стол + слот не повторяются."""
        _check_unique_pairs(value)
        return value


class BookingUpdate(BaseModel):
    """Частичное обновление брони."""

    tables_slots: list[BookingTableSlot] | None = Field(
        default=None,
        min_length=1,
    )
    guest_number: int | None = Field(default=None, gt=0)
    note: str | None = None
    status: BookingStatus | None = None
    booking_date: date | None = None
    is_active: bool | None = None

    @field_validator('tables_slots')
    @classmethod
    def unique_pairs(
        cls,
        value: list[BookingTableSlot] | None,
    ) -> list[BookingTableSlot] | None:
        """Пары стол + слот не повторяются."""
        if value is not None:
            _check_unique_pairs(value)
        return value


class BookingInfo(BaseModel):
    """Бронь в ответе API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    user: UserShortInfo
    cafe: CafeShortInfo
    # В модели связь называется table_slots, в API tables_slots
    tables_slots: list[BookingTableSlotShortInfo] = Field(
        validation_alias=AliasChoices('tables_slots', 'table_slots'),
    )
    guest_number: int
    note: str | None = None
    status: BookingStatus
    booking_date: date
    is_active: bool
    created_at: datetime
    updated_at: datetime
