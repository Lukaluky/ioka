import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.domain.offer import Offer


@dataclass(frozen=True)
class PassengerCounts:
    adults: int
    children: int = 0
    infants: int = 0

    @property
    def total(self) -> int:
        return self.adults + self.children + self.infants


@dataclass(frozen=True)
class SearchParams:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    passengers: PassengerCounts
    cabin: str
    # Валюта агента: цены оффера должны приходить уже в ней, а не в валюте провайдера.
    currency: str


class SearchStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class SearchResult:
    search_id: UUID
    agent_id: UUID
    status: SearchStatus
    offers: list[Offer] = field(default_factory=list)
    reason: str | None = None


def compute_cache_key(params: SearchParams) -> str:
    """Ключ кэша офферов по нормализованным параметрам поиска (SPEC §6.2)."""
    normalized = {
        "origin": params.origin.upper(),
        "destination": params.destination.upper(),
        "departure_date": params.departure_date.isoformat(),
        "return_date": params.return_date.isoformat() if params.return_date else None,
        "adults": params.passengers.adults,
        "children": params.passengers.children,
        "infants": params.passengers.infants,
        "cabin": params.cabin.lower(),
        "currency": params.currency.upper(),
    }
    raw = json.dumps(normalized, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()
