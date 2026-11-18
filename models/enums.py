from enum import StrEnum


class UserRole(StrEnum):
    """Роль пользователя."""

    ADMIN = 'ADMIN'
    MANAGER = 'MANAGER'
    USER = 'USER'


class BookingStatus(StrEnum):
    """Состояние брони."""

    BOOKING = 'BOOKING'
    CANCELED = 'CANCELED'
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'


class ReminderKind(StrEnum):
    """Тип напоминания."""

    DAY = 'DAY'
    HOUR = 'HOUR'
