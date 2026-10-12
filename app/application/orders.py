import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.application.offers import GetOfferDetail
from app.application.ports import IdempotencyKeyConflict, UnitOfWork
from app.domain.agent import Agent
from app.domain.errors import IdempotencyKeyReused, OrderNotFound, OrderValidationError
from app.domain.idempotency import IdempotencyKeyRecord
from app.domain.offer import FareFamily, OfferDetail
from app.domain.order import (
    Contact,
    Order,
    OrderStatus,
    Passenger,
    PassengerType,
    is_latin_name,
    passenger_type_matches_age,
)

MAX_TOTAL_PASSENGERS = 9


@dataclass(frozen=True)
class CreateOrderInput:
    offer_id: UUID
    fare_family: str
    passengers: list[Passenger]
    contact: Contact


def compute_request_hash(payload: dict[str, Any]) -> str:
    """Канонический JSON (сортированные ключи, без пробелов) -> sha256 (SPEC §8)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_fare_family(detail: OfferDetail, code: str) -> FareFamily:
    for fare in detail.fare_families:
        if fare.code == code:
            return fare
    raise OrderValidationError(f"Тариф {code} недоступен для этого оффера")


def _validate_passenger(passenger: Passenger, departure_date: date) -> None:
    if not is_latin_name(passenger.first_name) or not is_latin_name(passenger.last_name):
        raise OrderValidationError("Имя и фамилия должны быть латиницей")
    if passenger.document_expiry < departure_date:
        raise OrderValidationError("Документ не действует на дату вылета")
    if not passenger_type_matches_age(passenger.type, passenger.birth_date, departure_date):
        raise OrderValidationError(
            f"Возраст пассажира не соответствует типу {passenger.type.value}"
        )


def _validate_passenger_counts(passengers: list[Passenger]) -> None:
    # offer_id не хранит исходный search_id, поэтому сверяем состав пассажиров с общими
    # бизнес-правилами (как при поиске), а не буквально с конкретным поиском.
    adults = sum(1 for p in passengers if p.type == PassengerType.ADT)
    infants = sum(1 for p in passengers if p.type == PassengerType.INF)
    if adults < 1:
        raise OrderValidationError("Нужен хотя бы один взрослый пассажир")
    if infants > adults:
        raise OrderValidationError("Младенцев не может быть больше взрослых")
    if len(passengers) > MAX_TOTAL_PASSENGERS:
        raise OrderValidationError(f"Слишком много пассажиров (максимум {MAX_TOTAL_PASSENGERS})")


class CreateOrder:
    def __init__(
        self, uow: UnitOfWork, offer_lookup: GetOfferDetail, order_ttl_minutes: int
    ) -> None:
        self._uow = uow
        self._offer_lookup = offer_lookup
        self._order_ttl_minutes = order_ttl_minutes

    async def execute(
        self,
        agent: Agent,
        idempotency_key: str,
        payload: CreateOrderInput,
        request_hash: str,
    ) -> tuple[Order, bool]:
        existing = await self._uow.idempotency_keys.get(agent.id, idempotency_key)
        if existing is not None:
            return await self._replay(existing, request_hash)

        offer_detail = await self._offer_lookup.execute(payload.offer_id)
        fare = _find_fare_family(offer_detail, payload.fare_family)
        if fare.price.currency != agent.currency:
            raise OrderValidationError("Валюта оффера не совпадает с валютой агента")

        departure_date = offer_detail.offer.segments[0].departure_utc.date()
        for passenger in payload.passengers:
            _validate_passenger(passenger, departure_date)
        _validate_passenger_counts(payload.passengers)

        now = datetime.now(UTC)
        order = Order(
            id=uuid4(),
            agent_id=agent.id,
            offer_id=payload.offer_id,
            fare_family=fare.code,
            status=OrderStatus.BOOKED,
            passengers=payload.passengers,
            contact=payload.contact,
            price=fare.price,
            expires_at=now + timedelta(minutes=self._order_ttl_minutes),
            created_at=now,
        )

        await self._uow.orders.add(order)
        await self._uow.orders.add_status_history(order.id, None, OrderStatus.BOOKED, "created")

        try:
            await self._uow.idempotency_keys.add(agent.id, idempotency_key, request_hash, order.id)
        except IdempotencyKeyConflict:
            await self._uow.rollback()
            existing = await self._uow.idempotency_keys.get(agent.id, idempotency_key)
            if existing is None:
                raise
            return await self._replay(existing, request_hash)

        await self._uow.commit()
        return order, True

    async def _replay(
        self, existing: IdempotencyKeyRecord, request_hash: str
    ) -> tuple[Order, bool]:
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReused
        order = await self._uow.orders.get(existing.order_id)
        if order is None:
            raise OrderNotFound
        return order, False


class GetOrder:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, agent_id: UUID, order_id: UUID) -> Order:
        order = await self._uow.orders.get(order_id)
        if order is None or order.agent_id != agent_id:
            raise OrderNotFound

        now = datetime.now(UTC)
        if order.status == OrderStatus.BOOKED and order.expires_at <= now:
            order.transition_to(OrderStatus.EXPIRED)
            await self._uow.orders.add_status_history(
                order.id, OrderStatus.BOOKED, OrderStatus.EXPIRED, "ttl_expired"
            )
            await self._uow.orders.update_status(order)
            await self._uow.commit()
        return order
