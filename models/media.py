from __future__ import annotations

import uuid

from sqlalchemy import UUID, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base_model import Base


class Media(Base):
    """Загруженный медиафайл.

    Поля:
        id: UUID4 идентификатор файла.
        path: путь к файлу в файловом хранилище.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    path: Mapped[str] = mapped_column(String(255))
