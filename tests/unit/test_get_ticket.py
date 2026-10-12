from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.tickets import GetTicket
from app.domain.errors import InvalidOrderStatus, OrderNotFound, TicketNotReady
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType


def _make_order(agent_id: UUID, status: OrderStatus) -> Order:
    return Order(
        id=uuid4(),
        agent_id=agent_id,
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
        price=Money(Decimal("100"), "USD"),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_at=datetime.now(UTC),
    )


class FakeOrders:
    def __init__(self, order: Order) -> None:
        self.order = order

    async def get(self, order_id: UUID):
        return self.order if order_id == self.order.id else None


class FakeTickets:
    def __init__(self, pdf: bytes | None) -> None:
        self.pdf = pdf

    async def get_pdf(self, order_id: UUID) -> bytes | None:
        return self.pdf


class FakeUnitOfWork:
    def __init__(self, order: Order, pdf: bytes | None) -> None:
        self.orders = FakeOrders(order)
        self.tickets = FakeTickets(pdf)


async def test_unknown_order_raises_not_found() -> None:
    order = _make_order(uuid4(), OrderStatus.ISSUED)
    use_case = GetTicket(FakeUnitOfWork(order, b"%PDF-1.4"))

    with pytest.raises(OrderNotFound):
        await use_case.execute(uuid4(), uuid4())


async def test_foreign_agent_raises_not_found() -> None:
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.ISSUED)
    use_case = GetTicket(FakeUnitOfWork(order, b"%PDF-1.4"))

    with pytest.raises(OrderNotFound):
        await use_case.execute(uuid4(), order.id)


async def test_not_issued_order_raises_invalid_status() -> None:
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.BOOKED)
    use_case = GetTicket(FakeUnitOfWork(order, None))

    with pytest.raises(InvalidOrderStatus):
        await use_case.execute(owner_id, order.id)


async def test_issued_without_pdf_raises_ticket_not_ready() -> None:
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.ISSUED)
    use_case = GetTicket(FakeUnitOfWork(order, None))

    with pytest.raises(TicketNotReady):
        await use_case.execute(owner_id, order.id)


async def test_issued_with_pdf_returns_bytes() -> None:
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.ISSUED)
    use_case = GetTicket(FakeUnitOfWork(order, b"%PDF-1.4 content"))

    result = await use_case.execute(owner_id, order.id)

    assert result == b"%PDF-1.4 content"
