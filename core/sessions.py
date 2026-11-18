from time import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from core.auth_errors import auth_unavailable
from core.settings import Settings, settings

_CHECK_SESSION = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('PTTL', KEYS[1]) > 0 and 1 or 0
"""
_REFRESH_SESSION = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('PTTL', KEYS[1]) <= 0 then return 0 end
return redis.call('PEXPIRE', KEYS[1], ARGV[2])
"""
_DELETE_USER_SESSIONS = """
local deleted = 0
for _, key in ipairs(KEYS) do
    if redis.call('GET', key) == ARGV[1] then
        deleted = deleted + redis.call('DEL', key)
    end
end
return deleted
"""


class RedisSessionStore:
    """Хранит связь jti → ID пользователя; пароль и сам JWT не сохраняются."""

    def __init__(self, client: Redis, prefix: str, ttl_seconds: int) -> None:
        """Принимает клиент Redis и параметры отдельного пространства сессий."""
        self.client = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds

    def key(self, jti: str) -> str:
        """Возвращает ключ одной сессии."""
        return f'{self.prefix}:{jti}'

    def remaining_ttl_ms(self, expires_at: int) -> int:
        """Ограничивает окно бездействия абсолютным сроком JWT."""
        return max(0, min(self.ttl_seconds * 1000, int((expires_at - time()) * 1000)))

    async def create(self, jti: str, user_id: int, expires_at: int) -> None:
        """Создаёт сессию перед выдачей токена, не перезаписывая существующий jti."""
        ttl = self.remaining_ttl_ms(expires_at)
        if ttl == 0:
            raise auth_unavailable()
        try:
            created = await self.client.set(self.key(jti), str(user_id), px=ttl, nx=True)
        except RedisError:
            raise auth_unavailable() from None
        if not created:
            raise auth_unavailable()

    async def is_active(self, jti: str, user_id: int) -> bool:
        """Проверяет владельца и положительный TTL атомарно, без продления."""
        try:
            return bool(await self.client.eval(_CHECK_SESSION, 1, self.key(jti), str(user_id)))
        except RedisError:
            raise auth_unavailable() from None

    async def refresh(self, jti: str, user_id: int, expires_at: int) -> bool:
        """Продлевает только ещё существующую сессию того же пользователя."""
        ttl = self.remaining_ttl_ms(expires_at)
        if ttl == 0:
            return False
        try:
            return bool(await self.client.eval(_REFRESH_SESSION, 1, self.key(jti), str(user_id), ttl))
        except RedisError:
            raise auth_unavailable() from None

    async def revoke_user(self, user_id: int) -> None:
        """Удаляет все сессии пользователя, включая выданные до внедрения USR-02.

        Вызывается под блокировкой строки User, общей с входом. SCAN выполняется порциями,
        Lua проверяет владельца перед удалением. Чужие ключи не удаляются.
        """
        try:
            batch = []
            async for key in self.client.scan_iter(match=f'{self.prefix}:*', count=100):
                batch.append(key)
                if len(batch) == 100:
                    await self.client.eval(_DELETE_USER_SESSIONS, len(batch), *batch, str(user_id))
                    batch = []
            if batch:
                await self.client.eval(_DELETE_USER_SESSIONS, len(batch), *batch, str(user_id))
        except RedisError:
            raise auth_unavailable() from None


def create_session_store(config: Settings = settings) -> RedisSessionStore:
    """Создаёт ленивый клиент; недоступность Redis не мешает запуску публичных ручек."""
    client = Redis(
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_db,
        password=config.redis_password.get_secret_value() if config.redis_password else None,
        ssl=config.redis_ssl,
        decode_responses=True,
        socket_connect_timeout=config.redis_socket_timeout_seconds,
        socket_timeout=config.redis_socket_timeout_seconds,
        max_connections=50,
    )
    return RedisSessionStore(client, config.redis_session_prefix, config.redis_session_ttl_seconds)
