from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.outbox import OutboxEvent
from app.domain.transaction import Transaction
from app.infrastructure.db.models import OutboxModel, TransactionModel


class SqlTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, transaction: Transaction) -> None:
        self._session.add(
            TransactionModel(
                id=transaction.id,
                agent_id=transaction.agent_id,
                order_id=transaction.order_id,
                kind=transaction.kind.value,
                amount=transaction.amount,
                currency=transaction.currency,
                balance_after=transaction.balance_after,
                created_at=transaction.created_at,
            )
        )
        await self._session.flush()


class SqlOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event_type: str, payload: dict[str, Any]) -> None:
        self._session.add(OutboxModel(id=uuid4(), event_type=event_type, payload=payload))
        await self._session.flush()

    async def fetch_unpublished_for_update(self, limit: int) -> list[OutboxEvent]:
        stmt = (
            select(OutboxModel)
            .where(OutboxModel.published.is_(False))
            .order_by(OutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        return [
            OutboxEvent(
                id=model.id,
                event_type=model.event_type,
                payload=model.payload,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]

    async def mark_published(self, event_id: UUID) -> None:
        model = await self._session.get(OutboxModel, event_id)
        if model is None:
            return
        model.published = True
        await self._session.flush()
