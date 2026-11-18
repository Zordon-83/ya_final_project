from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import UUID, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base_model import Base

if TYPE_CHECKING:
    from .cafe import Cafe
    from .media import Media


class Action(Base):
    """Акция кафе.

    Поля:
        id: целочисленный идентификатор акции.
        description: описание акции.
        photo_id: необязательная ссылка на запись Media.
        is_active: признак действующей записи.
        created_at: время создания записи.
        updated_at: время последнего обновления записи.
    """

    description: Mapped[str] = mapped_column(Text)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('medias.id'),
    )

    photo: Mapped['Media | None'] = relationship()
    action_cafes: Mapped[list['ActionCafe']] = relationship(
        back_populates='action',
    )
    cafes: Mapped[list['Cafe']] = relationship(
        secondary='action_cafes',
        primaryjoin='Action.id == ActionCafe.action_id',
        secondaryjoin=('(Cafe.id == ActionCafe.cafe_id) & ActionCafe.is_active.is_(True)'),
        viewonly=True,
    )


class ActionCafe(Base):
    """Связь акции с кафе.

    Поля:
        id: идентификатор записи связи.
        action_id: идентификатор акции.
        cafe_id: идентификатор кафе.
        is_active: признак действующей записи связи.
        created_at: время создания связи.
        updated_at: время последнего обновления связи.
    """

    __tablename__ = 'action_cafes'

    action_id: Mapped[int] = mapped_column(ForeignKey('actions.id'))
    cafe_id: Mapped[int] = mapped_column(ForeignKey('cafes.id'))

    action: Mapped[Action] = relationship(
        back_populates='action_cafes',
    )
    cafe: Mapped['Cafe'] = relationship(
        back_populates='action_cafes',
    )

    __table_args__ = (
        UniqueConstraint(
            'action_id',
            'cafe_id',
            name='uq_action_cafes',
        ),
    )
