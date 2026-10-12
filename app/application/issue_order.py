from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.ports import AirProvider, UnitOfWork
from app.domain.errors import (
    InsufficientFunds,
    InvalidOrderStatus,
    IssueInProgress,
    OrderExpired,
    OrderNotFound,
    ProviderIssueFailed,
)
from app.domain.order import Order, OrderStatus
from app.domain.transaction import Transaction, TransactionKind


class IssueOrder:
    """SPEC §10: две транзакции БД, вызов провайдера строго между ними (вне транзакции)."""

    def __init__(self, uow: UnitOfWork, provider: AirProvider) -> None:
        self._uow = uow
        self._provider = provider

    async def execute(self, agent_id: UUID, order_id: UUID) -> Order:
        order = await self._uow.orders.get_for_update(order_id)
        if order is None or order.agent_id != agent_id:
            raise OrderNotFound

        if order.status == OrderStatus.ISSUED:
            # Идемпотентность: повторный issue уже выписанного заказа ничего не списывает.
            return order
        if order.status == OrderStatus.ISSUING:
            raise IssueInProgress
        if order.status != OrderStatus.BOOKED:
            raise InvalidOrderStatus(f"Заказ в статусе {order.status.value}, выписка невозможна")

        now = datetime.now(UTC)
        if order.expires_at <= now:
            order.transition_to(OrderStatus.EXPIRED)
            await self._uow.orders.update_status(order)
            await self._uow.orders.add_status_history(
                order.id, OrderStatus.BOOKED, OrderStatus.EXPIRED, "ttl_expired"
            )
            await self._uow.commit()
            raise OrderExpired

        agent = await self._uow.agents.get_for_update(agent_id)
        if agent is None or agent.balance < order.price.amount:
            raise InsufficientFunds

        # Транзакция 1: списание баланса, DEBIT, BOOKED -> ISSUING.
        new_balance = agent.balance - order.price.amount
        await self._uow.agents.update_balance(agent_id, new_balance)
        await self._uow.transactions.add(
            Transaction(
                id=uuid4(),
                agent_id=agent_id,
                order_id=order.id,
                kind=TransactionKind.DEBIT,
                amount=order.price.amount,
                currency=order.price.currency,
                balance_after=new_balance,
                created_at=now,
            )
        )
        order.transition_to(OrderStatus.ISSUING)
        await self._uow.orders.update_status(order)
        await self._uow.orders.add_status_history(
            order.id, OrderStatus.BOOKED, OrderStatus.ISSUING, "issue_started"
        )
        await self._uow.commit()

        try:
            ticket_numbers = await self._provider.issue(
                order.id, order.offer_id, order.fare_family, order.passengers, order.contact
            )
        except Exception:
            await self._refund(agent_id, order)
            raise ProviderIssueFailed from None

        # Транзакция 2 (успех): ISSUING -> ISSUED, номера билетов, событие в outbox.
        order.ticket_numbers = ticket_numbers
        order.transition_to(OrderStatus.ISSUED)
        await self._uow.orders.set_ticket_numbers(order.id, ticket_numbers)
        await self._uow.orders.update_status(order)
        await self._uow.orders.add_status_history(
            order.id, OrderStatus.ISSUING, OrderStatus.ISSUED, "issued"
        )
        await self._uow.outbox.add("ticket.generate", {"order_id": str(order.id)})
        await self._uow.commit()
        return order

    async def _refund(self, agent_id: UUID, order: Order) -> None:
        # Транзакция 2 (ошибка/таймаут провайдера): возврат денег, ISSUING -> ISSUE_FAILED.
        agent = await self._uow.agents.get_for_update(agent_id)
        assert agent is not None
        new_balance = agent.balance + order.price.amount
        await self._uow.agents.update_balance(agent_id, new_balance)
        await self._uow.transactions.add(
            Transaction(
                id=uuid4(),
                agent_id=agent_id,
                order_id=order.id,
                kind=TransactionKind.REFUND,
                amount=order.price.amount,
                currency=order.price.currency,
                balance_after=new_balance,
                created_at=datetime.now(UTC),
            )
        )
        order.transition_to(OrderStatus.ISSUE_FAILED)
        await self._uow.orders.update_status(order)
        await self._uow.orders.add_status_history(
            order.id, OrderStatus.ISSUING, OrderStatus.ISSUE_FAILED, "provider_issue_failed"
        )
        await self._uow.commit()
