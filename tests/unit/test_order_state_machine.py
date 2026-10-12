from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.errors import InvalidOrderStatus
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType


def _make_order(status: OrderStatus = OrderStatus.BOOKED) -> Order:
    return Order(
        id=uuid4(),
        agent_id=uuid4(),
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
                document_expiry=date(2030, 1, 1),
            )
        ],
        contact=Contact(email="a@example.com", phone="+77001234567"),
        price=Money(Decimal("100"), "USD"),
        expires_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


def test_booked_to_issuing_allowed() -> None:
    order = _make_order(OrderStatus.BOOKED)
    order.transition_to(OrderStatus.ISSUING)
    assert order.status == OrderStatus.ISSUING


def test_booked_to_expired_allowed() -> None:
    order = _make_order(OrderStatus.BOOKED)
    order.transition_to(OrderStatus.EXPIRED)
    assert order.status == OrderStatus.EXPIRED


def test_issuing_to_issued_allowed() -> None:
    order = _make_order(OrderStatus.ISSUING)
    order.transition_to(OrderStatus.ISSUED)
    assert order.status == OrderStatus.ISSUED


def test_issuing_to_issue_failed_allowed() -> None:
    order = _make_order(OrderStatus.ISSUING)
    order.transition_to(OrderStatus.ISSUE_FAILED)
    assert order.status == OrderStatus.ISSUE_FAILED


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (OrderStatus.BOOKED, OrderStatus.ISSUED),
        (OrderStatus.ISSUED, OrderStatus.BOOKED),
        (OrderStatus.ISSUED, OrderStatus.ISSUING),
        (OrderStatus.EXPIRED, OrderStatus.ISSUING),
        (OrderStatus.ISSUE_FAILED, OrderStatus.ISSUING),
    ],
)
def test_disallowed_transitions_raise(start: OrderStatus, target: OrderStatus) -> None:
    order = _make_order(start)
    with pytest.raises(InvalidOrderStatus):
        order.transition_to(target)
