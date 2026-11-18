"""События изменений публикуются только после успешного commit."""

from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from core.logging import actor_context, current_actor, event_fields, log_event


def discard_changes(session: Session, previous_transaction: SessionTransaction) -> None:
    """При rollback savepoint сохраняет события внешней транзакции."""
    if previous_transaction.parent is None:
        session.info.pop('audit_events', None)
        return
    remaining = []
    for entry in session.info.get('audit_events', []):
        transaction = entry[0]
        while transaction is not None and transaction is not previous_transaction:
            transaction = transaction.parent
        if transaction is None:
            remaining.append(entry)
    session.info['audit_events'] = remaining


def queue_change(session: AsyncSession, action: str, entity: str, entity_id: int | UUID) -> None:
    """Сохраняет событие и снимок actor в текущей единице работы."""
    event_fields(action, entity, 'success', entity_id=entity_id)
    transaction = session.sync_session.get_nested_transaction() or session.sync_session.get_transaction()
    if transaction is None:
        raise RuntimeError('Событие изменения требует активной транзакции')
    if not session.info.get('audit_rollback_listener'):
        event.listen(session.sync_session, 'after_soft_rollback', discard_changes)
        session.info['audit_rollback_listener'] = True
    session.info.setdefault('audit_events', []).append((
        transaction,
        action,
        entity,
        entity_id,
        current_actor(),
    ))


async def commit_with_audit(session: AsyncSession) -> None:
    """При ошибке commit ни одно событие успеха не публикуется."""
    await session.commit()
    for _, action, entity, entity_id, actor in session.info.pop('audit_events', []):
        with actor_context(actor):
            log_event(action, entity, 'success', entity_id=entity_id)
