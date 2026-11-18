from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .enums import UserRole
from core.base_model import Base

if TYPE_CHECKING:
    from .booking import Booking
    from .cafe import CafeManager


class User(Base):
    """Пользователь сервиса.

    Поля:
        id: целочисленный идентификатор пользователя.
        username: отображаемое имя пользователя.
        email: необязательный уникальный адрес электронной почты.
        phone: необязательный уникальный номер телефона.
        password_hash: хеш пароля для входа.
        role: роль пользователя: ADMIN, MANAGER или USER.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    username: Mapped[str] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(15), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name='user_role'),
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )

    cafe_managers: Mapped[list['CafeManager']] = relationship(
        back_populates='user',
    )
    bookings: Mapped[list['Booking']] = relationship(
        back_populates='user',
    )

    __table_args__ = (
        CheckConstraint(
            'email IS NOT NULL OR phone IS NOT NULL',
            name='ck_users_email_or_phone',
        ),
    )
