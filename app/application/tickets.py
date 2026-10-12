from uuid import UUID

from app.application.ports import UnitOfWork
from app.domain.errors import InvalidOrderStatus, OrderNotFound, TicketNotReady
from app.domain.order import OrderStatus


class GetTicket:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, agent_id: UUID, order_id: UUID) -> bytes:
        order = await self._uow.orders.get(order_id)
        if order is None or order.agent_id != agent_id:
            raise OrderNotFound
        if order.status != OrderStatus.ISSUED:
            raise InvalidOrderStatus(f"Билет недоступен для заказа в статусе {order.status.value}")

        pdf = await self._uow.tickets.get_pdf(order_id)
        if pdf is None:
            raise TicketNotReady
        return pdf
