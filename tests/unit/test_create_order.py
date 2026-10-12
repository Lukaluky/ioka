from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.offers import GetOfferDetail
from app.application.orders import CreateOrder, CreateOrderInput, compute_request_hash
from app.application.ports import IdempotencyKeyConflict
from app.domain.agent import Agent
from app.domain.errors import IdempotencyKeyReused, OrderValidationError
from app.domain.idempotency import IdempotencyKeyRecord
from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType


class FakeOrderRepository:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}
        self.history: list[tuple] = []

    async def add(self, order: Order) -> None:
        self.orders[order.id] = order

    async def get(self, order_id: UUID) -> Order | None:
        return self.orders.get(order_id)

    async def update_status(self, order: Order) -> None:
        self.orders[order.id] = order

    async def add_status_history(self, order_id, from_status, to_status, reason) -> None:
        self.history.append((order_id, from_status, to_status, reason))


class FakeIdempotencyKeyRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[UUID, str], IdempotencyKeyRecord] = {}

    async def get(self, agent_id: UUID, key: str) -> IdempotencyKeyRecord | None:
        return self.records.get((agent_id, key))

    async def add(self, agent_id: UUID, key: str, request_hash: str, order_id: UUID) -> None:
        if (agent_id, key) in self.records:
            raise IdempotencyKeyConflict
        self.records[(agent_id, key)] = IdempotencyKeyRecord(
            agent_id, key, request_hash, order_id, datetime.now(UTC)
        )


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.orders = FakeOrderRepository()
        self.idempotency_keys = FakeIdempotencyKeyRepository()
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


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


def _make_offer_detail(currency: str = "USD", departure_in_days: int = 30) -> OfferDetail:
    departure = datetime.now(UTC) + timedelta(days=departure_in_days)
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


def _make_agent(currency: str = "USD") -> Agent:
    return Agent(
        id=uuid4(),
        login="agent1",
        password_hash="x",
        name="Agent",
        balance=Decimal("1000"),
        currency=currency,
        is_active=True,
        created_at=datetime.now(UTC),
    )


def _make_passenger(
    passenger_type: PassengerType = PassengerType.ADT,
    birth_date: date = date(1990, 1, 1),
    first_name: str = "IVAN",
    last_name: str = "IVANOV",
    document_expiry: date = date(2099, 1, 1),
) -> Passenger:
    return Passenger(
        type=passenger_type,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        gender="M",
        citizenship="KZ",
        document_number="N1",
        document_expiry=document_expiry,
    )


def _make_input(detail: OfferDetail, **overrides) -> CreateOrderInput:
    base = dict(
        offer_id=detail.offer.offer_id,
        fare_family="STANDARD",
        passengers=[_make_passenger()],
        contact=Contact(email="a@example.com", phone="+77001234567"),
    )
    base.update(overrides)
    return CreateOrderInput(**base)  # type: ignore[arg-type]


def _make_use_case(detail: OfferDetail) -> tuple[CreateOrder, FakeUnitOfWork]:
    uow = FakeUnitOfWork()
    offer_lookup = GetOfferDetail(StaticSearchStore(detail), UnusedProvider(), cache_ttl_seconds=60)
    use_case = CreateOrder(uow, offer_lookup, order_ttl_minutes=30)
    return use_case, uow


async def test_create_order_success() -> None:
    detail = _make_offer_detail()
    use_case, uow = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(detail)
    request_hash = compute_request_hash({"offer_id": str(order_input.offer_id)})

    order, created = await use_case.execute(agent, str(uuid4()), order_input, request_hash)

    assert created is True
    assert order.status == OrderStatus.BOOKED
    assert order.price.amount == Decimal("100")
    assert uow.committed is True
    assert uow.orders.history[0] == (order.id, None, OrderStatus.BOOKED, "created")


async def test_idempotent_replay_same_body_returns_existing_order() -> None:
    detail = _make_offer_detail()
    use_case, uow = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(detail)
    request_hash = compute_request_hash({"offer_id": str(order_input.offer_id)})
    idem_key = str(uuid4())

    first_order, first_created = await use_case.execute(agent, idem_key, order_input, request_hash)
    second_order, second_created = await use_case.execute(
        agent, idem_key, order_input, request_hash
    )

    assert first_created is True
    assert second_created is False
    assert second_order.id == first_order.id
    assert len(uow.orders.orders) == 1


async def test_idempotent_replay_different_body_raises_conflict() -> None:
    detail = _make_offer_detail()
    use_case, uow = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(detail)
    idem_key = str(uuid4())

    await use_case.execute(agent, idem_key, order_input, compute_request_hash({"a": 1}))

    with pytest.raises(IdempotencyKeyReused):
        await use_case.execute(agent, idem_key, order_input, compute_request_hash({"a": 2}))


async def test_unknown_fare_family_raises_validation_error() -> None:
    detail = _make_offer_detail()
    use_case, _ = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(detail, fare_family="UNKNOWN")

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")


async def test_currency_mismatch_raises_validation_error() -> None:
    detail = _make_offer_detail(currency="EUR")
    use_case, _ = _make_use_case(detail)
    agent = _make_agent(currency="USD")
    order_input = _make_input(detail)

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")


async def test_non_latin_name_raises_validation_error() -> None:
    detail = _make_offer_detail()
    use_case, _ = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(detail, passengers=[_make_passenger(first_name="Иван")])

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")


async def test_expired_document_raises_validation_error() -> None:
    detail = _make_offer_detail()
    use_case, _ = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(
        detail, passengers=[_make_passenger(document_expiry=date(2000, 1, 1))]
    )

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")


async def test_age_type_mismatch_raises_validation_error() -> None:
    detail = _make_offer_detail()
    use_case, _ = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(
        detail,
        passengers=[_make_passenger(passenger_type=PassengerType.CHD, birth_date=date(1990, 1, 1))],
    )

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")


async def test_too_many_infants_raises_validation_error() -> None:
    detail = _make_offer_detail()
    use_case, _ = _make_use_case(detail)
    agent = _make_agent()
    order_input = _make_input(
        detail,
        passengers=[
            _make_passenger(),
            _make_passenger(passenger_type=PassengerType.INF, birth_date=date(2025, 1, 1)),
            _make_passenger(passenger_type=PassengerType.INF, birth_date=date(2025, 1, 1)),
        ],
    )

    with pytest.raises(OrderValidationError):
        await use_case.execute(agent, str(uuid4()), order_input, "hash")
