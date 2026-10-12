from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.ledger_repository import SqlOutboxRepository, SqlTransactionRepository
from app.infrastructure.db.order_repository import SqlIdempotencyKeyRepository, SqlOrderRepository
from app.infrastructure.db.repositories import SqlAgentRepository
from app.infrastructure.db.ticket_repository import SqlTicketRepository


class SqlUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.orders = SqlOrderRepository(session)
        self.idempotency_keys = SqlIdempotencyKeyRepository(session)
        self.agents = SqlAgentRepository(session)
        self.transactions = SqlTransactionRepository(session)
        self.outbox = SqlOutboxRepository(session)
        self.tickets = SqlTicketRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
