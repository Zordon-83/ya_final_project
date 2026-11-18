from typing import Annotated

import phonenumbers
from pydantic import AfterValidator

from .constants import PHONE_MAX_LENGTH


def normalize_phone(value: str) -> str:
    """Проверяет международный номер целиком и возвращает его в формате E.164."""
    value = value.strip()
    match = next(iter(phonenumbers.PhoneNumberMatcher(value, None)), None)
    if match is None or match.start != 0 or match.end != len(value):
        raise ValueError('Укажите корректный номер телефона с кодом страны')
    normalized = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
    if len(normalized) > PHONE_MAX_LENGTH:
        raise ValueError(
            f'Номер с кодом страны и знаком + должен содержать не более {PHONE_MAX_LENGTH} символов',
        )
    return normalized


Phone = Annotated[str, AfterValidator(normalize_phone)]
