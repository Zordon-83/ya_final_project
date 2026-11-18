"""Точки вызова уведомлений и напоминаний по броням (заглушки до Celery)."""

import logging

logger = logging.getLogger(__name__)


async def on_booking_created(booking_id: int) -> None:  # TODO
    """Вызывается после успешного сохранения брони.

    Здесь будет постановка задач уведомления администраторам и создание
    напоминаний. Ошибки не должны ломать ответ клиенту, поэтому только лог.
    """
    try:
        logger.info(
            'Бронь %s создана: постановка уведомлений пока не реализована',
            booking_id,
        )
    except Exception:
        logger.exception('Не удалось поставить задачи по брони %s', booking_id)
