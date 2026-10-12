import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.errors import InvalidOrderStatus
from app.domain.money import Money

_LATIN_NAME_PATTERN = re.compile(r"^[A-Z][A-Z\s\-']*$", re.IGNORECASE)


class PassengerType(StrEnum):
    ADT = "ADT"
    CHD = "CHD"
    INF = "INF"


# Границы возраста на дату вылета: ADT 12+, CHD 2-11, INF <2 (SPEC §8).
_AGE_BOUNDS: dict[PassengerType, tuple[int, int | None]] = {
    PassengerType.INF: (0, 2),
    PassengerType.CHD: (2, 12),
    PassengerType.ADT: (12, None),
}


def is_latin_name(value: str) -> bool:
    return bool(_LATIN_NAME_PATTERN.fullmatch(value))


def calculate_age(birth_date: date, on_date: date) -> int:
    years = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def passenger_type_matches_age(
    passenger_type: PassengerType, birth_date: date, on_date: date
) -> bool:
    age = calculate_age(birth_date, on_date)
    lower, upper = _AGE_BOUNDS[passenger_type]
    if upper is None:
        return age >= lower
    return lower <= age < upper


@dataclass(frozen=True)
class Passenger:
    type: PassengerType
    first_name: str
    last_name: str
    birth_date: date
    gender: str
    citizenship: str
    document_number: str
    document_expiry: date


@dataclass(frozen=True)
class Contact:
    email: str
    phone: str


class OrderStatus(StrEnum):
    BOOKED = "BOOKED"
    ISSUING = "ISSUING"
    ISSUED = "ISSUED"
    ISSUE_FAILED = "ISSUE_FAILED"
    EXPIRED = "EXPIRED"


# SPEC §9. CANCELLED опционален и не реализован — нет эндпоинта, который бы в него переводил.
_ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.BOOKED: frozenset({OrderStatus.ISSUING, OrderStatus.EXPIRED}),
    OrderStatus.ISSUING: frozenset({OrderStatus.ISSUED, OrderStatus.ISSUE_FAILED}),
    OrderStatus.ISSUED: frozenset(),
    OrderStatus.ISSUE_FAILED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


@dataclass
class Order:
    id: UUID
    agent_id: UUID
    offer_id: UUID
    fare_family: str
    status: OrderStatus
    passengers: list[Passenger]
    contact: Contact
    price: Money
    expires_at: datetime
    created_at: datetime
    ticket_numbers: list[str] = field(default_factory=list)

    def transition_to(self, target: OrderStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS.get(self.status, frozenset()):
            raise InvalidOrderStatus(f"Переход {self.status.value} -> {target.value} недопустим")
        self.status = target
