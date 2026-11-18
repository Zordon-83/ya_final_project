from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from models.enums import UserRole

from core.constants import USERNAME_MAX_LENGTH
from core.phone import Phone


def validate_username(value: str) -> str:
    """Отклоняет краевые пробелы и непечатные символы в отображаемом имени."""
    if value != value.strip() or not value.isprintable():
        raise ValueError('Имя не должно содержать непечатные символы или пробелы по краям')
    return value


Username = Annotated[
    str,
    StringConstraints(min_length=1, max_length=USERNAME_MAX_LENGTH),
    AfterValidator(validate_username),
]


class AuthData(BaseModel):
    """Учётные данные для входа по email или телефону."""

    login: EmailStr | Phone
    password: SecretStr


class AuthToken(BaseModel):
    """Ответ на успешный вход."""

    access_token: str
    token_type: str


class _UserContacts(BaseModel):
    """Контактные данные, которые можно передать при регистрации или изменении пользователя."""

    email: EmailStr | None = None
    phone: Phone | None = None


class UserCreate(_UserContacts):
    """Данные для регистрации пользователя."""

    username: Username
    password: SecretStr

    @model_validator(mode='after')
    def require_contact(self) -> Self:
        """Проверяет, что пользователь указал хотя бы один контакт для входа."""
        if self.email is None and self.phone is None:
            raise ValueError('Для регистрации укажите email или телефон')
        return self


class UserUpdate(_UserContacts):
    """Поля частичного обновления пользователя."""

    username: Username | SkipJsonSchema[None] = None
    password: SecretStr | SkipJsonSchema[None] = None
    role: UserRole | SkipJsonSchema[None] = None
    is_active: bool | SkipJsonSchema[None] = None

    @field_validator('username', 'password', 'role', 'is_active', mode='before')
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        """Разрешает пропуск поля, но не очистку обязательного значения через null."""
        if value is None:
            raise ValueError('Поле можно пропустить, но нельзя передать null')
        return value


class UserShortInfo(BaseModel):
    """Краткая информация о пользователе во вложенных ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr | None = None
    phone: str | None = None


class UserInfo(UserShortInfo):
    """Информация о пользователе в ответе API."""

    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
