import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.application.offers import GetOfferDetail
from app.application.orders import CreateOrder, CreateOrderInput, compute_request_hash
from app.domain.agent import Agent
from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment
from app.domain.order import Contact, Passenger, PassengerType
from app.infrastructure.db.models import AgentModel, IdempotencyKeyModel, OrderModel
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.unit_of_work import SqlUnitOfWork


class StaticSearchStore:
    def __init__(self, detail: OfferDetail) -> None:
        self._detail = detail

    async def get_offer_detail(self, offer_id):
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


def _make_offer_detail(currency: str = "USD") -> OfferDetail:
    departure = datetime.now(UTC) + timedelta(days=30)
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
        min_price=Money(Decimal("100"), currency),
    )
    fare = FareFamily(
        code="STANDARD",
        name="Standard",
        price=Money(Decimal("100"), currency),
        baggage_kg=23,
        carry_on=True,
        refundable=False,
        exchangeable=True,
    )
    return OfferDetail(offer=offer, fare_families=[fare])


async def test_concurrent_create_with_same_key_creates_exactly_one_order() -> None:
    session_factory = get_session_factory()
    agent_id = uuid4()

    async with session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                login=f"concurrency-{agent_id}",
                password_hash="x",
                name="Concurrency Test",
                balance=Decimal("1000"),
                currency="USD",
                is_active=True,
            )
        )
        await session.commit()

    agent = Agent(
        id=agent_id,
        login="x",
        password_hash="x",
        name="x",
        balance=Decimal("1000"),
        currency="USD",
        is_active=True,
        created_at=datetime.now(UTC),
    )
    detail = _make_offer_detail()
    offer_lookup = GetOfferDetail(StaticSearchStore(detail), UnusedProvider(), cache_ttl_seconds=60)
    order_input = CreateOrderInput(
        offer_id=detail.offer.offer_id,
        fare_family="STANDARD",
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
    )
    request_hash = compute_request_hash({"offer_id": str(order_input.offer_id)})
    idempotency_key = str(uuid4())

    async def _run() -> tuple:
        async with session_factory() as session:
            uow = SqlUnitOfWork(session)
            use_case = CreateOrder(uow, offer_lookup, order_ttl_minutes=30)
            return await use_case.execute(agent, idempotency_key, order_input, request_hash)

    results = await asyncio.gather(_run(), _run())
    order_ids = {order.id for order, _ in results}

    try:
        assert len(order_ids) == 1
        async with session_factory() as session:
            rows = (
                (await session.execute(select(OrderModel).where(OrderModel.agent_id == agent_id)))
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        async with session_factory() as session:
            idem = await session.get(IdempotencyKeyModel, (agent_id, idempotency_key))
            if idem is not None:
                await session.delete(idem)
            for order_id in order_ids:
                order_model = await session.get(OrderModel, order_id)
                if order_model is not None:
                    await session.delete(order_model)
            agent_model = await session.get(AgentModel, agent_id)
            if agent_model is not None:
                await session.delete(agent_model)
            await session.commit()
