import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from app.domain.errors import OfferNotFound, ProviderError
from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment
from app.domain.order import Contact, Passenger
from app.domain.search import SearchParams

_AIRLINES = ("KC", "TK", "HY", "FZ", "PC")
_HUBS = ("IST", "DXB", "AUH", "SAW", "DOH")


@dataclass(frozen=True)
class MockProviderConfig:
    delay_min_seconds: float = 1.0
    delay_max_seconds: float = 3.0
    timeout_seconds: float = 5.0
    failure_rate: float = 0.0
    timeout_rate: float = 0.0


def _utc_offset_hours(iata_code: str) -> int:
    # Нет реальной базы часовых поясов аэропортов — смещение считается от кода,
    # чтобы локальное и UTC-время были разными, но стабильными для одного кода.
    return sum(ord(c) for c in iata_code) % 12


def _round_money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class MockAirProvider:
    """Имитация внешнего авиапровайдера: правдоподобные детерминированные данные.

    Детерминированность касается содержимого (авиакомпания, сегменты, цены) — оно
    зависит только от (origin, destination, departure_date). offer_id генерируется
    каждый раз новым (как и у реального провайдера), поэтому для get_offer офферы
    кэшируются в памяти инстанса на время его жизни.
    """

    def __init__(self, config: MockProviderConfig | None = None) -> None:
        self._config = config or MockProviderConfig()
        self._fault_rng = random.Random()
        self._offers: dict[UUID, OfferDetail] = {}

    async def search(self, params: SearchParams) -> list[Offer]:
        await self._simulate_network()
        details = self._generate_offers(params)
        for detail in details:
            self._offers[detail.offer.offer_id] = detail
        return [detail.offer for detail in details]

    async def get_offer(self, offer_id: UUID) -> OfferDetail:
        await self._simulate_network()
        detail = self._offers.get(offer_id)
        if detail is None:
            raise OfferNotFound
        return detail

    async def issue(
        self,
        order_id: UUID,
        offer_id: UUID,
        fare_family: str,
        passengers: list[Passenger],
        contact: Contact,
    ) -> list[str]:
        await self._simulate_network()
        return [self._generate_ticket_number() for _ in passengers]

    def _generate_ticket_number(self) -> str:
        # Условный числовой код авиакомпании (999) + 10-значный серийный номер,
        # по форме похоже на реальный IATA ticket number.
        serial = self._fault_rng.randint(0, 9_999_999_999)
        return f"999{serial:010d}"

    async def _simulate_network(self) -> None:
        if self._fault_rng.random() < self._config.timeout_rate:
            # Специально дольше внешнего таймаута: вызывающая сторона должна отменить ожидание.
            await asyncio.sleep(self._config.timeout_seconds + 10)
            return
        delay = self._fault_rng.uniform(
            self._config.delay_min_seconds, self._config.delay_max_seconds
        )
        if delay > 0:
            await asyncio.sleep(delay)
        if self._fault_rng.random() < self._config.failure_rate:
            raise ProviderError("Имитация сбоя внешнего провайдера")

    def _generate_offers(self, params: SearchParams) -> list[OfferDetail]:
        seed = f"{params.origin}|{params.destination}|{params.departure_date.isoformat()}"
        rng = random.Random(seed)
        count = rng.randint(3, 6)
        return [self._build_offer(params, rng) for _ in range(count)]

    def _build_offer(self, params: SearchParams, rng: random.Random) -> OfferDetail:
        airline = rng.choice(_AIRLINES)
        stops = 1 if rng.random() < 0.3 else 0
        base_hour = rng.randint(0, 23)
        base_minute = rng.choice((0, 15, 30, 45))
        departure_utc = datetime(
            params.departure_date.year,
            params.departure_date.month,
            params.departure_date.day,
            base_hour,
            base_minute,
            tzinfo=UTC,
        )

        if stops == 0:
            segments = [
                self._build_segment(rng, airline, params.origin, params.destination, departure_utc)
            ]
        else:
            hub_pool = [h for h in _HUBS if h not in (params.origin, params.destination)]
            hub = rng.choice(hub_pool)
            first = self._build_segment(rng, airline, params.origin, hub, departure_utc)
            layover_minutes = rng.randint(60, 180)
            second_departure = first.arrival_utc + timedelta(minutes=layover_minutes)
            second = self._build_segment(rng, airline, hub, params.destination, second_departure)
            segments = [first, second]

        base_price = Decimal(rng.randint(100, 500))
        fare_families = [
            FareFamily(
                code="LIGHT",
                name="Light",
                price=Money(_round_money(base_price), params.currency),
                baggage_kg=0,
                carry_on=True,
                refundable=False,
                exchangeable=False,
            ),
            FareFamily(
                code="STANDARD",
                name="Standard",
                price=Money(_round_money(base_price * Decimal("1.3")), params.currency),
                baggage_kg=23,
                carry_on=True,
                refundable=False,
                exchangeable=True,
            ),
            FareFamily(
                code="FLEX",
                name="Flex",
                price=Money(_round_money(base_price * Decimal("1.7")), params.currency),
                baggage_kg=23,
                carry_on=True,
                refundable=True,
                exchangeable=True,
            ),
        ]

        offer = Offer(
            offer_id=uuid4(),
            airline=airline,
            segments=segments,
            stops=stops,
            cabin=params.cabin,
            min_price=fare_families[0].price,
        )
        return OfferDetail(offer=offer, fare_families=fare_families)

    @staticmethod
    def _build_segment(
        rng: random.Random, airline: str, origin: str, destination: str, departure_utc: datetime
    ) -> Segment:
        duration_minutes = rng.randint(90, 360)
        arrival_utc = departure_utc + timedelta(minutes=duration_minutes)
        return Segment(
            flight_number=f"{airline}{rng.randint(100, 999)}",
            airline=airline,
            origin=origin,
            destination=destination,
            departure_utc=departure_utc,
            departure_local=departure_utc + timedelta(hours=_utc_offset_hours(origin)),
            arrival_utc=arrival_utc,
            arrival_local=arrival_utc + timedelta(hours=_utc_offset_hours(destination)),
            duration_minutes=duration_minutes,
        )
