from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.offers import GetOfferDetail
from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from app.infrastructure.db.models import AgentModel, OrderModel, TicketModel
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.unit_of_work import SqlUnitOfWork
from app.worker.ticket_consumer import process_ticket_generate


class StaticSearchStore:
    def __init__(self, detail: OfferDetail) -> None:
        self._detail = detail

    async def get_offer_detail(self, offer_id: UUID) -> OfferDetail | None:
        return self._detail if offer_id == self._detail.offer.offer_id else None

    async def save_offer_detail(self, detail, ttl_seconds: int) -> None:
        pass

    async def save(self, result) -> None:
        pass

    async def get(self, search_id):
        return None

    async def get_cached_offers(self, cache_key: str):
        return None

    async def cache_offers(self, cache_key: str, offers, ttl_seconds: int) -> None:
        pass


class UnusedProvider:
    async def search(self, params):
        raise NotImplementedError

    async def get_offer(self, offer_id):
        raise NotImplementedError

    async def issue(self, order_id, offer_id, fare_family, passengers, contact):
        raise NotImplementedError


def _make_offer_detail() -> OfferDetail:
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
    return OfferDetail(offer=offer, fare_families=[fare])


async def _create_agent() -> UUID:
    agent_id = uuid4()
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                login=f"ticket-test-{agent_id}",
                password_hash="x",
                name="Ticket Test",
                balance=Decimal("1000"),
                currency="USD",
                is_active=True,
            )
        )
        await session.commit()
    return agent_id


async def _create_issued_order(agent_id: UUID, offer_id: UUID) -> UUID:
    order = Order(
        id=uuid4(),
        agent_id=agent_id,
        offer_id=offer_id,
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
                document_number="N1",
                document_expiry=date(2099, 1, 1),
            )
        ],
        contact=Contact(email="a@example.com", phone="+77001234567"),
        price=Money(Decimal("100"), "USD"),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_at=datetime.now(UTC),
        ticket_numbers=["9990000000001"],
    )
    session_factory = get_session_factory()
    async with session_factory() as session:
        uow = SqlUnitOfWork(session)
        await uow.orders.add(order)
        await uow.commit()
    return order.id


async def test_process_ticket_generate_creates_pdf_and_is_idempotent() -> None:
    detail = _make_offer_detail()
    agent_id = await _create_agent()
    order_id = await _create_issued_order(agent_id, detail.offer.offer_id)
    offer_lookup = GetOfferDetail(StaticSearchStore(detail), UnusedProvider(), cache_ttl_seconds=60)
    session_factory = get_session_factory()
    payload = {"order_id": str(order_id)}

    try:
        await process_ticket_generate(payload, session_factory, offer_lookup)

        async with session_factory() as session:
            ticket = await session.get(TicketModel, order_id)
            assert ticket is not None
            assert ticket.pdf.startswith(b"%PDF")
            assert str(order_id).encode() in bytes(ticket.pdf)
            first_created_at = ticket.created_at

        # Повторное сообщение не должно создать дубль / изменить существующий билет.
        await process_ticket_generate(payload, session_factory, offer_lookup)

        async with session_factory() as session:
            ticket = await session.get(TicketModel, order_id)
            assert ticket is not None
            assert ticket.created_at == first_created_at
    finally:
        async with session_factory() as session:
            ticket = await session.get(TicketModel, order_id)
            if ticket is not None:
                await session.delete(ticket)
            order_model = await session.get(OrderModel, order_id)
            if order_model is not None:
                await session.delete(order_model)
            agent_model = await session.get(AgentModel, agent_id)
            if agent_model is not None:
                await session.delete(agent_model)
            await session.commit()
