from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.orders import GetOrder
from app.domain.errors import OrderNotFound
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from tests.unit.test_create_order import FakeUnitOfWork


def _make_order(agent_id, status: OrderStatus, expires_at: datetime) -> Order:
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
        expires_at=expires_at,
        created_at=datetime.now(UTC),
    )


async def test_unknown_order_raises_not_found() -> None:
    use_case = GetOrder(FakeUnitOfWork())

    with pytest.raises(OrderNotFound):
        await use_case.execute(uuid4(), uuid4())


async def test_foreign_agent_raises_not_found() -> None:
    uow = FakeUnitOfWork()
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.BOOKED, datetime.now(UTC) + timedelta(minutes=30))
    uow.orders.orders[order.id] = order
    use_case = GetOrder(uow)

    with pytest.raises(OrderNotFound):
        await use_case.execute(uuid4(), order.id)


async def test_owner_gets_own_order() -> None:
    uow = FakeUnitOfWork()
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.BOOKED, datetime.now(UTC) + timedelta(minutes=30))
    uow.orders.orders[order.id] = order
    use_case = GetOrder(uow)

    result = await use_case.execute(owner_id, order.id)

    assert result.id == order.id
    assert result.status == OrderStatus.BOOKED


async def test_lazy_expiry_transitions_booked_to_expired() -> None:
    uow = FakeUnitOfWork()
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.BOOKED, datetime.now(UTC) - timedelta(minutes=1))
    uow.orders.orders[order.id] = order
    use_case = GetOrder(uow)

    result = await use_case.execute(owner_id, order.id)

    assert result.status == OrderStatus.EXPIRED
    assert uow.committed is True
    assert uow.orders.history[-1][2] == OrderStatus.EXPIRED


async def test_issued_order_is_not_affected_by_ttl() -> None:
    uow = FakeUnitOfWork()
    owner_id = uuid4()
    order = _make_order(owner_id, OrderStatus.ISSUED, datetime.now(UTC) - timedelta(minutes=1))
    uow.orders.orders[order.id] = order
    use_case = GetOrder(uow)

    result = await use_case.execute(owner_id, order.id)

    assert result.status == OrderStatus.ISSUED
