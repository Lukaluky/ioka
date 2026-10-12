from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import TicketModel


class SqlTicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, order_id: UUID) -> bool:
        model = await self._session.get(TicketModel, order_id)
        return model is not None

    async def get_pdf(self, order_id: UUID) -> bytes | None:
        model = await self._session.get(TicketModel, order_id)
        return bytes(model.pdf) if model is not None else None

    async def save(self, order_id: UUID, pdf: bytes) -> None:
        self._session.add(TicketModel(order_id=order_id, pdf=pdf))
        await self._session.flush()
