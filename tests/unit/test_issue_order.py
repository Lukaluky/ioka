from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.issue_order import IssueOrder
from app.domain.errors import (
    InsufficientFunds,
    InvalidOrderStatus,
    IssueInProgress,
    OrderExpired,
    OrderNotFound,
    ProviderIssueFailed,
)
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from app.domain.transaction import TransactionKind


class FakeAgentRepository:
    def __init__(self, balance: Decimal, currency: str = "USD") -> None:
        self.agent_id = uuid4()
        self.balance = balance
        self.currency = currency

    async def get_by_login(self, login: str):
        raise NotImplementedError

    async def get_by_id(self, agent_id: UUID):
        raise NotImplementedError

    async def get_for_update(self, agent_id: UUID):
        from app.domain.agent import Agent

        if agent_id != self.agent_id:
            return None
        return Agent(
            id=self.agent_id,
            login="agent1",
            password_hash="x",
            name="Agent",
            balance=self.balance,
            currency=self.currency,
            is_active=True,
            created_at=datetime.now(UTC),
        )

    async def update_balance(self, agent_id: UUID, new_balance: Decimal) -> None:
        self.balance = new_balance


class FakeOrderRepository:
    def __init__(self, order: Order) -> None:
        self.order = order
        self.history: list[tuple] = []

    async def add(self, order: Order) -> None:
        self.order = order

    async def get(self, order_id: UUID) -> Order | None:
        return self.order if order_id == self.order.id else None

    async def get_for_update(self, order_id: UUID) -> Order | None:
        return self.order if order_id == self.order.id else None

    async def update_status(self, order: Order) -> None:
        self.order.status = order.status

    async def set_ticket_numbers(self, order_id: UUID, ticket_numbers: list[str]) -> None:
        self.order.ticket_numbers = ticket_numbers

    async def add_status_history(self, order_id, from_status, to_status, reason) -> None:
        self.history.append((order_id, from_status, to_status, reason))


class FakeTransactionRepository:
    def __init__(self) -> None:
        self.transactions: list = []

    async def add(self, transaction) -> None:
        self.transactions.append(transaction)


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.events: list = []

    async def add(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class FakeIdempotencyKeyRepository:
    async def get(self, agent_id, key):
        return None

    async def add(self, agent_id, key, request_hash, order_id) -> None:
        pass


class FakeUnitOfWork:
    def __init__(self, order: Order, balance: Decimal, currency: str = "USD") -> None:
        self.orders = FakeOrderRepository(order)
        self.agents = FakeAgentRepository(balance, currency)
        self.transactions = FakeTransactionRepository()
        self.outbox = FakeOutboxRepository()
        self.idempotency_keys = FakeIdempotencyKeyRepository()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class SuccessProvider:
    def __init__(self, ticket_numbers: list[str]) -> None:
        self._ticket_numbers = ticket_numbers

    async def search(self, params):
        raise NotImplementedError

    async def get_offer(self, offer_id):
        raise NotImplementedError

    async def issue(self, order_id, offer_id, fare_family, passengers, contact) -> list[str]:
        return self._ticket_numbers


class FailingProvider:
    async def search(self, params):
        raise NotImplementedError

    async def get_offer(self, offer_id):
        raise NotImplementedError

    async def issue(self, order_id, offer_id, fare_family, passengers, contact):
        raise RuntimeError("provider down")


def _make_order(
    status: OrderStatus = OrderStatus.BOOKED,
    price: Decimal = Decimal("100"),
    currency: str = "USD",
    expires_in_minutes: int = 30,
    agent_id: UUID | None = None,
) -> Order:
    return Order(
        id=uuid4(),
        agent_id=agent_id or uuid4(),
        offer_id=uuid4(),
        fare_family="STANDARD",
        status=status,
        passengers=[
            Passenger(
                type=PassengerType.ADT,
                first_name="IVAN",
                last_name="IVANOV",
                birth_date=date(1990, 1, 1),
                gender="M",
                citizenship="KZ",
                document_number="N1",
                document_expiry=date(2099, 1, 1),
            )
        ],
        contact=Contact(email="a@example.com", phone="+77001234567"),
        price=Money(price, currency),
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        created_at=datetime.now(UTC),
    )


async def test_successful_issue_debits_and_marks_issued() -> None:
    order = _make_order()
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider(["999-0000000001"]))

    result = await use_case.execute(uow.agents.agent_id, order.id)

    assert result.status == OrderStatus.ISSUED
    assert result.ticket_numbers == ["999-0000000001"]
    assert uow.agents.balance == Decimal("900")
    assert len(uow.transactions.transactions) == 1
    assert uow.transactions.transactions[0].kind == TransactionKind.DEBIT
    assert uow.transactions.transactions[0].balance_after == Decimal("900")
    assert uow.outbox.events == [("ticket.generate", {"order_id": str(order.id)})]
    assert uow.commits == 2


async def test_already_issued_is_idempotent_and_does_not_debit_again() -> None:
    order = _make_order(status=OrderStatus.ISSUED)
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider(["999-0000000001"]))

    result = await use_case.execute(uow.agents.agent_id, order.id)

    assert result.status == OrderStatus.ISSUED
    assert uow.agents.balance == Decimal("1000")
    assert uow.transactions.transactions == []


async def test_issuing_in_progress_raises_conflict() -> None:
    order = _make_order(status=OrderStatus.ISSUING)
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider([]))

    with pytest.raises(IssueInProgress):
        await use_case.execute(uow.agents.agent_id, order.id)


async def test_issue_failed_order_cannot_be_reissued() -> None:
    order = _make_order(status=OrderStatus.ISSUE_FAILED)
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider([]))

    with pytest.raises(InvalidOrderStatus):
        await use_case.execute(uow.agents.agent_id, order.id)


async def test_expired_order_transitions_and_raises() -> None:
    order = _make_order(expires_in_minutes=-1)
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider([]))

    with pytest.raises(OrderExpired):
        await use_case.execute(uow.agents.agent_id, order.id)

    assert order.status == OrderStatus.EXPIRED
    assert uow.transactions.transactions == []


async def test_insufficient_funds_raises_and_does_not_debit() -> None:
    order = _make_order(price=Decimal("500"))
    uow = FakeUnitOfWork(order, balance=Decimal("100"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider([]))

    with pytest.raises(InsufficientFunds):
        await use_case.execute(uow.agents.agent_id, order.id)

    assert uow.agents.balance == Decimal("100")
    assert uow.transactions.transactions == []


async def test_provider_failure_refunds_and_marks_issue_failed() -> None:
    order = _make_order(price=Decimal("100"))
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, FailingProvider())

    with pytest.raises(ProviderIssueFailed):
        await use_case.execute(uow.agents.agent_id, order.id)

    assert order.status == OrderStatus.ISSUE_FAILED
    assert uow.agents.balance == Decimal("1000")
    kinds = [t.kind for t in uow.transactions.transactions]
    assert kinds == [TransactionKind.DEBIT, TransactionKind.REFUND]


async def test_foreign_agent_raises_not_found() -> None:
    order = _make_order()
    uow = FakeUnitOfWork(order, balance=Decimal("1000"))
    order.agent_id = uow.agents.agent_id
    use_case = IssueOrder(uow, SuccessProvider([]))

    with pytest.raises(OrderNotFound):
        await use_case.execute(uuid4(), order.id)
