from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, Segment
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from app.infrastructure.ticketing.pdf import generate_ticket_pdf


def _make_order_and_offer() -> tuple[Order, Offer, FareFamily]:
    departure = datetime.now(UTC) + timedelta(days=10)
    segment = Segment(
        flight_number="KC100",
        airline="KC",
        origin="ALA",
        destination="IST",
        departure_utc=departure,
        departure_local=departure,
        arrival_utc=departure + timedelta(hours=3),
        arrival_local=departure + timedelta(hours=3),
        duration_minutes=180,
    )
    offer = Offer(
        offer_id=uuid4(),
        airline="KC",
        segments=[segment],
        stops=0,
        cabin="economy",
        min_price=Money(Decimal("100"), "USD"),
    )
    fare = FareFamily(
        code="STANDARD",
        name="Standard",
        price=Money(Decimal("100"), "USD"),
        baggage_kg=23,
        carry_on=True,
        refundable=False,
        exchangeable=True,
    )
    order = Order(
        id=uuid4(),
        agent_id=uuid4(),
        offer_id=offer.offer_id,
        fare_family="STANDARD",
        status=OrderStatus.ISSUED,
        passengers=[
            Passenger(
                type=PassengerType.ADT,
                first_name="IVAN",
                last_name="IVANOV",
                birth_date=date(1990, 1, 1),
                gender="M",
                citizenship="KZ",
                document_number="N12345678",
                document_expiry=date(2099, 1, 1),
            )
        ],
        contact=Contact(email="a@example.com", phone="+77001234567"),
        price=Money(Decimal("100"), "USD"),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_at=datetime.now(UTC),
        ticket_numbers=["9990000000001"],
    )
    return order, offer, fare


def test_generate_ticket_pdf_is_valid_and_contains_order_data() -> None:
    order, offer, fare = _make_order_and_offer()

    pdf_bytes = generate_ticket_pdf(order, offer, fare)

    assert pdf_bytes.startswith(b"%PDF")
    assert str(order.id).encode() in pdf_bytes
    assert b"9990000000001" in pdf_bytes
    assert b"IVANOV" in pdf_bytes


def test_generate_ticket_pdf_without_fare_does_not_crash() -> None:
    order, offer, _ = _make_order_and_offer()

    pdf_bytes = generate_ticket_pdf(order, offer, None)

    assert pdf_bytes.startswith(b"%PDF")
