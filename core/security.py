from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import SecretStr

from models.enums import UserRole

from core.settings import Settings

password_hasher = PasswordHash.recommended()
_dummy_password_hash = password_hasher.hash(token_urlsafe(32))


def verify_password(password: SecretStr, password_hash: str | None) -> bool:
    """Проверяет Argon2id; при отсутствии пользователя выполняет проверку фиктивного хеша."""
    try:
        valid = password_hasher.verify(password.get_secret_value(), password_hash or _dummy_password_hash)
    except UnknownHashError:
        password_hasher.verify(password.get_secret_value(), _dummy_password_hash)
        return False
    return valid and password_hash is not None


def create_access_token(user_id: int, role: UserRole, config: Settings) -> str:
    """Подписывает JWT с уникальной сессией и абсолютным сроком действия."""
    if config.jwt_secret_key is None:
        raise ValueError('JWT_SECRET_KEY не настроен')
    now = datetime.now(UTC)
    payload = {
        'sub': str(user_id),
        'user_id': user_id,
        'role': role.value,
        'jti': str(uuid4()),
        'iat': now,
        'nbf': now,
        'exp': now + timedelta(seconds=config.jwt_access_token_ttl_seconds),
    }
    return jwt.encode(payload, config.jwt_secret_key.get_secret_value(), algorithm=config.jwt_algorithm)


def decode_access_token(token: str, config: Settings) -> dict:
    """Проверяет подпись, сроки и обязательные claims; алгоритм задаёт только сервер."""
    if config.jwt_secret_key is None:
        raise jwt.InvalidTokenError('JWT is disabled')
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret_key.get_secret_value(),
            algorithms=[config.jwt_algorithm],
            options={'require': ['sub', 'user_id', 'role', 'jti', 'iat', 'nbf', 'exp']},
        )
    except (TypeError, ValueError, OverflowError):
        raise jwt.InvalidTokenError('Invalid claim type') from None
    integer_fields = ('user_id', 'iat', 'nbf', 'exp')
    if any(type(claims[field]) is not int for field in integer_fields):
        raise jwt.InvalidTokenError('Invalid claim type')
    if not 0 < claims['user_id'] < 2**31 or claims['sub'] != str(claims['user_id']):
        raise jwt.InvalidTokenError('Invalid subject')
    if claims['exp'] <= claims['iat'] or claims['nbf'] >= claims['exp']:
        raise jwt.InvalidTokenError('Invalid lifetime')
    try:
        session_id = UUID(claims['jti'])
        UserRole(claims['role'])
    except (ValueError, TypeError, AttributeError):
        raise jwt.InvalidTokenError('Invalid session or role') from None
    if session_id.version != 4 or str(session_id) != claims['jti']:
        raise jwt.InvalidTokenError('Invalid session ID')
    return claims
