import argparse
import asyncio
import json
import sys
from datetime import date

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from services.demo_seed import DemoSeedError, seed_demo


async def run(start_date: date | None) -> dict:
    """Фиксирует весь набор одной транзакцией и закрывает пул подключения."""
    from core.db import async_engine, session_maker

    try:
        async with session_maker.begin() as session:
            return await seed_demo(session, start_date)
    finally:
        await async_engine.dispose()


def main() -> int:
    """Создаёт демо-данные; ошибки БД не раскрывают параметры подключения и хеши."""
    parser = argparse.ArgumentParser(description='USR-07: идемпотентные данные учебного стенда')
    parser.add_argument(
        '--start-date',
        type=date.fromisoformat,
        help='Первая дата броней YYYY-MM-DD (по умолчанию завтра, МСК)',
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.start_date))
    except DemoSeedError as error:
        print(f'Демо-данные не записаны: {error}', file=sys.stderr)
        return 1
    except (SQLAlchemyError, ValidationError):
        print(
            'Демо-данные не записаны: проверьте настройки БД, миграции и ограничения данных.',
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
