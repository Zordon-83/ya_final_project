from __future__ import annotations

from asyncio import to_thread
from hashlib import sha256

from fastapi import status
from sqlalchemy import BigInteger, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import UserRole
from models.user import User
from schemas.user import UserCreate, UserInfo, UserUpdate

from core.exceptions import CustomException
from core.logging import log_event
from core.security import password_hasher
from core.sessions import RedisSessionStore


def validate_contact_update(
    update: UserUpdate,
    *,
    current_email: str | None,
    current_phone: str | None,
) -> None:
    """Проверяет, что после частичного обновления останется контакт для входа.

    Сервис записи должен читать текущие контакты под блокировкой строки в той же транзакции.
    Пропущенное поле сохраняет прежнее значение, явно переданный null удаляет контакт.
    """
    fields = update.model_fields_set
    email = update.email if 'email' in fields else current_email
    phone = update.phone if 'phone' in fields else current_phone
    if not email and not phone:
        raise ValueError('У пользователя должен остаться email или телефон для входа')


def invalid_user_data() -> CustomException:
    """Не раскрывает значение контакта или текст ограничения БД при конфликте."""
    return CustomException(
        code=status.HTTP_400_BAD_REQUEST,
        message='Имя или контакт уже используются',
        status_code=status.HTTP_400_BAD_REQUEST,
    )


async def lock_email(session: AsyncSession, email: str | None) -> None:
    """Сериализует регистронезависимую проверку email между параллельными записями API."""
    if email is not None:
        digest = sha256(f'users/email/{email.lower()}'.encode()).digest()
        key = int.from_bytes(digest[:8], 'big', signed=True)
        await session.execute(select(func.pg_advisory_xact_lock(cast(key, BigInteger))))


async def check_unique_user(session: AsyncSession, user: User) -> None:
    """Проверяет имя и нормализованные контакты, не учитывая обновляемую запись."""
    matches = [User.username == user.username]
    if user.email is not None:
        matches.append(func.lower(User.email) == user.email.lower())
    if user.phone is not None:
        matches.append(User.phone == user.phone)
    query = select(User.id).where(or_(*matches)).limit(1)
    if user.id is not None:
        query = query.where(User.id != user.id)
    with session.no_autoflush:
        if await session.scalar(query) is not None:
            raise invalid_user_data()


def validate_user_values(data: UserCreate | UserUpdate) -> None:
    """Проверяет размер email по модели и непустой пароль до обращения к хешированию."""
    if data.email is not None and len(data.email) > 255:
        raise CustomException(
            code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message='Email слишком длинный',
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if data.password is not None and not 1 <= len(data.password.get_secret_value()) <= 1024:
        raise CustomException(
            code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message='Пароль должен содержать от 1 до 1024 символов',
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


async def create_user(session: AsyncSession, data: UserCreate) -> UserInfo:
    """Создаёт только активного USER; ограничения БД закрывают гонки одинаковых имён/телефонов."""
    validate_user_values(data)
    password_hash = await to_thread(password_hasher.hash, data.password.get_secret_value())
    user = User(
        username=data.username,
        email=str(data.email).lower() if data.email is not None else None,
        phone=data.phone,
        password_hash=password_hash,
        role=UserRole.USER,
        is_active=True,
    )
    try:
        await lock_email(session, user.email)
        await check_unique_user(session, user)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        result = UserInfo.model_validate(user)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise invalid_user_data() from None
    log_event('created', 'user', 'success', entity_id=result.id)
    return result


async def get_user(session: AsyncSession, user_id: int, *, for_update: bool = False) -> User:
    """Получает запись; при изменении блокирует и перечитывает её поверх identity map."""
    query = select(User).where(User.id == user_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    user = await session.scalar(query)
    if user is None:
        raise CustomException(
            code=status.HTTP_404_NOT_FOUND,
            message='Пользователь не найден',
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return user


async def list_users(session: AsyncSession) -> list[User]:
    """Возвращает массив пользователей в стабильном порядке согласно контракту API."""
    return list((await session.scalars(select(User).order_by(User.id))).all())


async def update_user(
    session: AsyncSession,
    user_id: int,
    data: UserUpdate,
    store: RedisSessionStore,
) -> tuple[UserInfo, bool]:
    """Обновляет запись под блокировкой и отзывает сессии до подтверждения транзакции."""
    validate_user_values(data)
    password_hash = (
        await to_thread(password_hasher.hash, data.password.get_secret_value())
        if data.password is not None
        else None
    )
    try:
        user = await get_user(session, user_id, for_update=True)
        try:
            validate_contact_update(data, current_email=user.email, current_phone=user.phone)
        except ValueError:
            raise CustomException(
                code=status.HTTP_400_BAD_REQUEST,
                message='Укажите email или телефон для входа',
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from None
        values = data.model_dump(exclude_unset=True, exclude={'password'})
        if 'email' in values and values['email'] is not None:
            values['email'] = str(values['email']).lower()
        await lock_email(session, values.get('email'))
        for field, value in values.items():
            setattr(user, field, value)
        if password_hash is not None:
            user.password_hash = password_hash
        await check_unique_user(session, user)
        await session.flush()
        await session.refresh(user)
        result = UserInfo.model_validate(user)
        revoke_sessions = password_hash is not None or data.is_active is False
        if revoke_sessions:
            await store.revoke_user(user.id)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise invalid_user_data() from None
    except CustomException:
        await session.rollback()
        raise
    action = 'deactivated' if data.is_active is False else 'updated'
    log_event(action, 'user', 'success', entity_id=result.id)
    return result, revoke_sessions


async def delete_user(session: AsyncSession, user_id: int, store: RedisSessionStore) -> UserInfo:
    """Мягко удаляет пользователя: сохраняет запись, блокирует вход и отзывает все сессии.

    Повторный вызов безопасен. Ошибка Redis откатывает изменение активности тем же механизмом,
    что используется при смене пароля и административном обновлении.
    """
    user, _ = await update_user(session, user_id, UserUpdate(is_active=False), store)
    return user
