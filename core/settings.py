from pathlib import Path
from typing import Literal, Self

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .phone import Phone

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Настройки приложения."""

    # Общие настройки
    title: str = 'Система бронирования мест в кафе'
    version: str = '0.0.3'
    description: str = 'API backend для управления бронированием мест в кафе'

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_server: str = 'localhost'
    postgres_port: int = 5432

    jwt_secret_key: SecretStr | None = Field(default=None, min_length=32, repr=False)
    jwt_algorithm: Literal['HS256'] = 'HS256'
    jwt_access_token_ttl_seconds: int = Field(default=3600, gt=0, le=31_536_000)

    redis_host: str = 'redis'
    redis_port: int = Field(default=6379, gt=0, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_password: SecretStr | None = Field(default=None, repr=False)
    redis_ssl: bool = False
    redis_session_prefix: str = Field(default='session', pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    redis_session_ttl_seconds: int = Field(default=1800, gt=0, le=31_536_000)
    redis_socket_timeout_seconds: float = Field(default=2, gt=0, le=30)

    reminder_day_days: int = Field(default=1, gt=0)
    reminder_hour_hours: int = Field(default=1, gt=0)

    first_admin_email: EmailStr | None = None
    first_admin_phone: Phone | None = None
    first_admin_password: SecretStr | None = None
    first_admin_lock_key: int | None = Field(default=None, ge=-(2**63), lt=2**63, repr=False)

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / '../infra/.env',
        env_file_encoding='utf-8',
        extra='ignore',
        hide_input_in_errors=True,
    )

    @field_validator('jwt_secret_key', 'redis_password', mode='before')
    @classmethod
    def empty_jwt_secret(cls, value: object) -> object:
        """Пустой ключ отключает выдачу JWT без влияния на остальные компоненты."""
        return None if value == '' else value

    @field_validator(
        'first_admin_email',
        'first_admin_phone',
        'first_admin_password',
        'first_admin_lock_key',
        mode='before',
    )
    @classmethod
    def empty_admin_value(cls, value: object) -> object:
        """Считает пустое значение в .env незаполненной настройкой."""
        return None if value == '' else value

    @model_validator(mode='after')
    def validate_first_admin(self) -> Self:
        """Проверяет настройки контактов, пароля и координации реплик."""
        has_contact = self.first_admin_email is not None or self.first_admin_phone is not None
        if has_contact != (self.first_admin_password is not None):
            raise ValueError(
                'Задайте FIRST_ADMIN_PASSWORD и контакт: FIRST_ADMIN_EMAIL или FIRST_ADMIN_PHONE',
            )
        if has_contact and self.first_admin_lock_key is None:
            raise ValueError('Для создания первого администратора задайте FIRST_ADMIN_LOCK_KEY')
        return self

    @property
    def db_url(self) -> str:
        """Строка подключения к БД."""
        return (
            f'postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@'
            f'{self.postgres_server}:{self.postgres_port}/{self.postgres_db}'
        )


settings = Settings()
