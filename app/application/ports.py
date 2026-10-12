from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.domain.agent import Agent
from app.domain.idempotency import IdempotencyKeyRecord
from app.domain.location import Location
from app.domain.offer import Offer, OfferDetail
from app.domain.order import Contact, Order, OrderStatus, Passenger
from app.domain.outbox import OutboxEvent
from app.domain.search import SearchParams, SearchResult
from app.domain.transaction import Transaction


class AgentRepository(Protocol):
    async def get_by_login(self, login: str) -> Agent | None: ...

    async def get_by_id(self, agent_id: UUID) -> Agent | None: ...

    async def get_for_update(self, agent_id: UUID) -> Agent | None: ...

    async def update_balance(self, agent_id: UUID, new_balance: Decimal) -> None: ...


class PasswordHasher(Protocol):
    # Фиксированный хэш для несуществующего логина: проверка пароля идёт и в этом случае,
    # чтобы время ответа не отличалось от случая с верным логином (защита от перебора логинов).
    dummy_hash: str

    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, password_hash: str) -> bool: ...


class TokenService(Protocol):
    def create_access_token(self, agent_id: UUID) -> str: ...

    def decode_access_token(self, token: str) -> UUID: ...


class LocationRepository(Protocol):
    async def search(self, query: str, limit: int) -> list[Location]: ...

    async def get_by_code(self, iata_code: str) -> Location | None: ...


class AirProvider(Protocol):
    # book не реализован: заказ создаётся локально (SPEC §8), провайдер вызывается только
    # при выписке (issue).
    async def search(self, params: SearchParams) -> list[Offer]: ...

    async def get_offer(self, offer_id: UUID) -> OfferDetail: ...

    async def issue(
        self,
        order_id: UUID,
        offer_id: UUID,
        fare_family: str,
        passengers: list[Passenger],
        contact: Contact,
    ) -> list[str]: ...


class SearchStore(Protocol):
    async def save(self, result: SearchResult) -> None: ...

    async def get(self, search_id: UUID) -> SearchResult | None: ...

    async def get_cached_offers(self, cache_key: str) -> list[Offer] | None: ...

    async def cache_offers(self, cache_key: str, offers: list[Offer], ttl_seconds: int) -> None: ...

    async def save_offer_detail(self, detail: OfferDetail, ttl_seconds: int) -> None: ...

    async def get_offer_detail(self, offer_id: UUID) -> OfferDetail | None: ...


class TaskQueue(Protocol):
    async def publish_search_requested(
        self, search_id: UUID, agent_id: UUID, params: SearchParams
    ) -> None: ...


class IdempotencyKeyConflict(Exception):
    """Поднимается реализацией IdempotencyKeyRepository при конфликте unique(agent_id, key)."""


class OrderRepository(Protocol):
    async def add(self, order: Order) -> None: ...

    async def get(self, order_id: UUID) -> Order | None: ...

    async def get_for_update(self, order_id: UUID) -> Order | None: ...

    async def update_status(self, order: Order) -> None: ...

    async def set_ticket_numbers(self, order_id: UUID, ticket_numbers: list[str]) -> None: ...

    async def add_status_history(
        self,
        order_id: UUID,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        reason: str | None,
    ) -> None: ...


class IdempotencyKeyRepository(Protocol):
    async def get(self, agent_id: UUID, key: str) -> IdempotencyKeyRecord | None: ...

    async def add(self, agent_id: UUID, key: str, request_hash: str, order_id: UUID) -> None: ...


class TransactionRepository(Protocol):
    async def add(self, transaction: Transaction) -> None: ...


class OutboxRepository(Protocol):
    async def add(self, event_type: str, payload: dict[str, Any]) -> None: ...

    async def fetch_unpublished_for_update(self, limit: int) -> list[OutboxEvent]: ...

    async def mark_published(self, event_id: UUID) -> None: ...


class TicketRepository(Protocol):
    async def exists(self, order_id: UUID) -> bool: ...

    async def get_pdf(self, order_id: UUID) -> bytes | None: ...

    async def save(self, order_id: UUID, pdf: bytes) -> None: ...


class UnitOfWork(Protocol):
    # Свойства, а не обычные атрибуты: иначе mypy требует точное совпадение типа (инвариантность)
    # и ругается на конкретные Sql*Repository, которые являются подтипами портов.
    @property
    def orders(self) -> OrderRepository: ...

    @property
    def idempotency_keys(self) -> IdempotencyKeyRepository: ...

    @property
    def agents(self) -> AgentRepository: ...

    @property
    def transactions(self) -> TransactionRepository: ...

    @property
    def outbox(self) -> OutboxRepository: ...

    @property
    def tickets(self) -> TicketRepository: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
