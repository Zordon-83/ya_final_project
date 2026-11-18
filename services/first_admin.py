from asyncio import to_thread

from pwdlib import PasswordHash
from pydantic import SecretStr
from sqlalchemy import BigInteger, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import UserRole
from models.user import User

from core.constants import FIRST_ADMIN_USERNAME

password_hasher = PasswordHash.recommended()


async def ensure_first_admin(
    session: AsyncSession,
    *,
    email: str | None,
    phone: str | None,
    password: SecretStr,
    lock_key: int,
) -> int | None:
    """Создаёт первого администратора в транзакции вызывающей стороны."""
    await session.execute(select(func.pg_advisory_xact_lock(cast(lock_key, BigInteger))))
    matches = [User.role == UserRole.ADMIN]
    if email is not None:
        matches.append(func.lower(User.email) == func.lower(email))
    if phone is not None:
        matches.append(User.phone == phone)
    existing = select(User.id).where(or_(*matches)).limit(1)
    if await session.scalar(existing) is not None:
        return None

    password_hash = await to_thread(password_hasher.hash, password.get_secret_value())
    create_admin = (
        insert(User)
        .values(
            username=FIRST_ADMIN_USERNAME,
            email=email,
            phone=phone,
            password_hash=password_hash,
            role=UserRole.ADMIN,
            is_active=True,
        )
        .on_conflict_do_nothing()
        .returning(User.id)
    )
    created_id = await session.scalar(create_admin)
    if created_id is None and await session.scalar(existing) is None:
        raise RuntimeError('Не удалось создать администратора: проверьте, свободно ли имя admin')
    return created_id
