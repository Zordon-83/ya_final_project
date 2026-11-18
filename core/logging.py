"""Единое безопасное логирование приложения и серверных процессов."""

import json
import logging
import os
import sys
import traceback
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import TextIO
from uuid import UUID

LOG_MAX_BYTES = 50 * 1024 * 1024
LOG_BACKUP_COUNT = 4  # Пять лог-файлов всего в каталоге: текущий и четыре архива.
_SOURCE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = (_SOURCE_DIR.parent if _SOURCE_DIR.name == 'src' else _SOURCE_DIR) / 'logs'
_LOCK = RLock()
_CONTEXT: ContextVar[MutableMapping[str, object] | None] = ContextVar('log_actor', default=None)
_HANDLERS: list[logging.Handler] = []
_CONFIG: tuple[object, ...] | None = None
_ACTIONS = frozenset({
    'application_starting',
    'application_started',
    'application_stopped',
    'startup_failed',
    'shutdown_failed',
    'http_request',
    'validation_failed',
    'business_rejected',
    'access_denied',
    'http_rejected',
    'server_error',
    'created',
    'updated',
    'deactivated',
    'canceled',
    'task_started',
    'task_finished',
    'task_failed',
})
_ENTITIES = frozenset({'application', 'http', 'user', 'cafe', 'table', 'slot', 'media', 'booking', 'task'})
_OUTCOMES = frozenset({'started', 'success', 'failure', 'denied'})
_SERVER_MESSAGES = {
    'Started server process [%d]': 'server_started',
    'Finished server process [%d]': 'server_stopped',
    'Waiting for application startup.': 'waiting_for_startup',
    'Application startup complete.': 'startup_complete',
    'Waiting for application shutdown.': 'waiting_for_shutdown',
    'Application shutdown complete.': 'shutdown_complete',
    'Shutting down': 'server_stopping',
}


class _SafeConsoleHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        """Не печатает исходный record при ошибке записи."""
        sys.__stderr__.write('Logging output failed\n')


class _SafeFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        """Сериализует запись/ротацию и закрывает файл перед освобождением OS-lock."""
        try:
            with _file_lock(Path(self.baseFilename).with_name('.application.lock')):
                try:
                    super().emit(record)
                finally:
                    if self.stream is not None:
                        self.stream.close()
                        self.stream = None
        except OSError:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        """Не раскрывает args/exception при заполнении диска или ошибке ротации."""
        sys.__stderr__.write('Log file write/rotation failed\n')


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Native-lock: msvcrt в Windows и flock в POSIX; освобождается и при аварии процесса."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'r+b') as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def actor_context(actor: MutableMapping[str, object] | None = None) -> Iterator[None]:
    """Изолирует actor HTTP-запроса или фоновой задачи и восстанавливает прежний."""
    token = _CONTEXT.set(actor)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_actor() -> MutableMapping[str, object] | None:
    """Возвращает независимый снимок actor для события после commit."""
    actor = _CONTEXT.get()
    return dict(actor) if actor is not None else None


@contextmanager
def system_task() -> Iterator[None]:
    """Изолирует фоновую операцию от унаследованного HTTP-actor."""
    with actor_context():
        log_event('task_started', 'task', 'started')
        try:
            yield
        except Exception as error:
            log_exception('task_failed', 'task', error)
            raise
        else:
            log_event('task_finished', 'task', 'success')


def bind_request_actor(scope: MutableMapping[str, object], *, user_id: int, username: str) -> None:
    """Вызывается только после авторизации; общий scope переживает дочерние ASGI-задачи."""
    if type(user_id) is not int or user_id <= 0 or not isinstance(username, str) or not username:
        raise ValueError('Требуются подтверждённые user_id и username')
    actor = scope.get('audit_actor')
    if not isinstance(actor, dict):
        raise RuntimeError('Не подключён RequestLoggingMiddleware')
    actor.update(actor='USER', user_id=user_id, username=username)


def event_fields(
    action: str,
    entity_type: str,
    outcome: str,
    *,
    entity_id: int | UUID | None = None,
    status_code: int | None = None,
) -> dict[str, object]:
    """Проверяет контракт до commit; данные запроса и ORM не принимает."""
    if action not in _ACTIONS or entity_type not in _ENTITIES or outcome not in _OUTCOMES:
        raise ValueError('Неизвестный тип события аудита')
    if (
        entity_id is not None
        and not isinstance(entity_id, UUID)
        and (type(entity_id) is not int or entity_id <= 0)
    ):
        raise ValueError('entity_id должен быть положительным целым или UUID')
    event = {'action': action, 'entity_type': entity_type, 'outcome': outcome, 'entity_id': entity_id}
    if status_code is not None:
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ValueError('Некорректный HTTP-статус')
        event['status_code'] = status_code
    return event


def log_event(
    action: str,
    entity_type: str,
    outcome: str,
    *,
    entity_id: int | UUID | None = None,
    level: int = logging.INFO,
    status_code: int | None = None,
) -> None:
    """Записывает событие через общий проверяемый контракт."""
    event = event_fields(action, entity_type, outcome, entity_id=entity_id, status_code=status_code)
    logging.getLogger('app.audit').log(level, action, extra={'audit_event': event})


def log_exception(action: str, entity_type: str, error: Exception) -> None:
    """Пишет тип и стек без сообщения, аргументов исключения и локальных переменных."""
    if getattr(error, '_cafe_error_logged', False):
        return
    if action not in _ACTIONS or entity_type not in _ENTITIES:
        raise ValueError('Неизвестный тип события ошибки')
    logging.getLogger('app.error').error(
        action,
        extra={'audit_event': {'action': action, 'entity_type': entity_type, 'outcome': 'failure'}},
        exc_info=(type(error), error, error.__traceback__),
    )
    error._cafe_error_logged = True


class _AlreadyLoggedFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Uvicorn не повторяет уже зафиксированную серверную ошибку."""
        error = record.exc_info[1] if record.exc_info else None
        return not (record.name.startswith('uvicorn') and getattr(error, '_cafe_error_logged', False))


class SafeFormatter(logging.Formatter):
    """JSON Lines с разрешёнными полями; произвольные сообщения и args не сериализуются."""

    @staticmethod
    def access_fields(args: object) -> dict[str, object]:
        """Из access-log берёт только разрешённые метод и статус."""
        fields = {'message': 'http_access'}
        if isinstance(args, tuple) and len(args) == 5:
            method, status = args[1], args[4]
            if method in ('GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'):
                fields['method'] = method
            if type(status) is int and 100 <= status <= 599:
                fields['status_code'] = status
        return fields

    def format(self, record: logging.LogRecord) -> str:
        """Не вызывает getMessage/formatException: они могут раскрыть входные данные."""
        actor = _CONTEXT.get()
        payload = {
            'timestamp': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'actor': actor.get('actor', 'ANONYMOUS') if actor is not None else 'SYSTEM',
            'user_id': actor.get('user_id') if actor else None,
            'username': actor.get('username') if actor else None,
        }
        event = getattr(record, 'audit_event', None)
        if isinstance(event, dict) and event.get('action') in _ACTIONS:
            payload['action'] = event['action']
            if event.get('entity_type') in _ENTITIES:
                payload['entity_type'] = event['entity_type']
            if event.get('outcome') in _OUTCOMES:
                payload['outcome'] = event['outcome']
            for field in ('entity_id', 'status_code'):
                if type(event.get(field)) is int:
                    payload[field] = event[field]
            if isinstance(event.get('entity_id'), UUID):
                payload['entity_id'] = str(event['entity_id'])
            payload['message'] = event['action']
        elif record.name == 'uvicorn.access':
            payload.update(self.access_fields(record.args))
        else:
            payload['message'] = (
                _SERVER_MESSAGES.get(record.msg, 'unstructured_message_omitted')
                if isinstance(record.msg, str)
                else 'unstructured_message_omitted'
            )
        if record.exc_info and record.exc_info[1] is not None:
            error = record.exc_info[1]
            payload['error_type'] = type(error).__name__
            payload['stack'] = [
                {'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=False)


def _resolve_level(level: str | int | None = None) -> int:
    selected = level if level is not None else os.getenv('LOG_LEVEL', 'INFO')
    if isinstance(selected, str):
        selected = logging.getLevelNamesMapping().get(selected.upper())
    if selected not in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
        raise ValueError('LOG_LEVEL: ожидается DEBUG, INFO, WARNING, ERROR или CRITICAL')
    return selected


def _prepare_handler(handler: logging.Handler, level: int) -> logging.Handler:
    handler.setLevel(level)
    handler.setFormatter(SafeFormatter())
    handler.addFilter(_AlreadyLoggedFilter())
    handler._cafe_owned = True
    return handler


def build_console_handler() -> logging.Handler:
    """Фабрика dictConfig для Uvicorn, в том числе reload-supervisor."""
    return _prepare_handler(_SafeConsoleHandler(sys.stderr), _resolve_level())


def build_file_handler() -> logging.Handler:
    """Фабрика dictConfig с общей безопасной ротацией процессов."""
    return _create_file_handler(
        Path(os.getenv('LOG_DIR', DEFAULT_LOG_DIR)).resolve(),
        _resolve_level(),
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
    )


def _create_file_handler(directory: Path, level: int, max_bytes: int, backup_count: int) -> logging.Handler:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with _file_lock(directory / '.application.lock'):
            with (directory / 'application.log').open('a', encoding='utf-8'):
                pass
        handler = _SafeFileHandler(
            directory / 'application.log',
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
            delay=True,
        )
    except OSError:
        raise RuntimeError('Не удалось открыть файл логов: проверьте LOG_DIR и права записи') from None
    return _prepare_handler(handler, level)


def setup_logging(
    *,
    log_dir: str | Path | None = None,
    level: str | int | None = None,
    stream: TextIO | None = None,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> None:
    """Настраивает root/Uvicorn с общей ротацией под межпроцессной блокировкой."""
    global _CONFIG
    directory = Path(log_dir if log_dir is not None else os.getenv('LOG_DIR', DEFAULT_LOG_DIR)).resolve()
    selected_level = _resolve_level(level)
    if max_bytes <= 0 or backup_count < 1:
        raise ValueError('Некорректные параметры ротации')
    target_stream = stream if stream is not None else sys.stderr
    config = (os.getpid(), directory, selected_level, id(target_stream), max_bytes, backup_count)
    with _LOCK:
        root = logging.getLogger()
        if _CONFIG != config or not all(handler in root.handlers for handler in _HANDLERS):
            file_handler = _create_file_handler(directory, selected_level, max_bytes, backup_count)
            console = _prepare_handler(_SafeConsoleHandler(target_stream), selected_level)
            for handler in set(_HANDLERS + root.handlers):
                if not getattr(handler, '_cafe_owned', False):
                    continue
                root.removeHandler(handler)
                handler.close()
            _HANDLERS[:] = [console, file_handler]
            _CONFIG = config
        # При повторном вызове также устраняем handlers, добавленные конфигурацией сервера.
        root.handlers[:] = _HANDLERS
        root.setLevel(selected_level)
        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True
            logger.setLevel(selected_level)
