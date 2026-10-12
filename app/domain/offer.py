from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.money import Money


@dataclass(frozen=True)
class Segment:
    flight_number: str
    airline: str
    origin: str
    destination: str
    departure_utc: datetime
    departure_local: datetime
    arrival_utc: datetime
    arrival_local: datetime
    duration_minutes: int


@dataclass(frozen=True)
class FareFamily:
    code: str
    name: str
    price: Money
    baggage_kg: int
    carry_on: bool
    refundable: bool
    exchangeable: bool


@dataclass(frozen=True)
class Offer:
    offer_id: UUID
    airline: str
    segments: list[Segment]
    stops: int
    cabin: str
    min_price: Money


@dataclass(frozen=True)
class OfferDetail:
    offer: Offer
    fare_families: list[FareFamily]
