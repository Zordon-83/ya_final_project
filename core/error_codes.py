"""Коды бизнес-ошибок бронирования."""

from enum import IntEnum


class ErrorCode(IntEnum):
    """Коды ошибок бронирования (предложены в BKG-02)."""

    CAFE_NOT_FOUND = 1001
    BOOKING_DATE_IN_PAST = 1003
    INVALID_GUEST_NUMBER = 1004
    TABLE_NOT_FOUND = 1005
    SLOT_NOT_FOUND = 1006
    TABLE_NOT_IN_CAFE = 1007
    SLOT_NOT_IN_CAFE = 1008
    CAPACITY_EXCEEDED = 1009
    TABLE_SLOT_OCCUPIED = 1010
    USER_BOOKING_OVERLAP = 1011
