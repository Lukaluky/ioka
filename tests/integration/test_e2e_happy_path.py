"""E2E happy path через httpx.AsyncClient (SPEC §13): login -> search -> poll -> offer detail ->
order -> issue -> ticket. Нет живого воркера в тестовом процессе, поэтому шаги, которые в проде
выполняет app/worker, здесь вызываются напрямую (process_message, relay_once,
process_ticket_generate) — сам HTTP-флоу через API при этом не упрощён."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from app.application.offers import GetOfferDetail
from app.config import get_settings
from app.domain.order import OrderStatus
from app.domain.search import SearchParams
from app.infrastructure.db.models import (
    AgentModel,
    IdempotencyKeyModel,
    OrderModel,
    OrderPassengerModel,
    OrderStatusHistoryModel,
    TicketModel,
    TransactionModel,
)
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.json_utils import to_jsonable
from app.infrastructure.providers.factory import build_air_provider
from app.infrastructure.redis_client import get_redis_client
from app.infrastructure.redis_store import RedisSearchStore
from app.infrastructure.security import BcryptPasswordHasher
from app.main import app, lifespan
from app.worker.main import process_message
from app.worker.outbox_relay import relay_once
from app.worker.ticket_consumer import process_ticket_generate


class _CapturingTaskQueue:
    """Подменяет реальный RabbitMQ: тест сам прогоняет шаг воркера над захваченным payload."""

    def __init__(self) -> None:
        self.last: dict[str, Any] | None = None

    async def publish_search_requested(
        self, search_id: UUID, agent_id: UUID, params: SearchParams
    ) -> None:
        self.last = {"search_id": search_id, "agent_id": agent_id, "params": params}


async def _create_agent(login: str, password: str) -> UUID:
    agent_id = uuid4()
    password_hash = await BcryptPasswordHasher().hash(password)
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                login=login,
                password_hash=password_hash,
                name="E2E Agent",
                balance=Decimal("100000"),
                currency="USD",
                is_active=True,
            )
        )
        await session.commit()
    return agent_id


async def _cleanup(agent_id: UUID, order_id: UUID | None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        if order_id is not None:
            for model in (
                TicketModel,
                TransactionModel,
                OrderStatusHistoryModel,
                OrderPassengerModel,
            ):
                await session.execute(model.__table__.delete().where(model.order_id == order_id))
            await session.execute(
                IdempotencyKeyModel.__table__.delete().where(
                    IdempotencyKeyModel.order_id == order_id
                )
            )
            await session.execute(OrderModel.__table__.delete().where(OrderModel.id == order_id))
        await session.execute(AgentModel.__table__.delete().where(AgentModel.id == agent_id))
        await session.commit()


async def test_full_happy_path_via_http() -> None:
    login = f"e2e-{uuid4()}"
    password = "e2e-password-123"
    agent_id = await _create_agent(login, password)

    settings = get_settings()
    search_store = RedisSearchStore(get_redis_client(), settings.search_ttl_seconds)
    provider = build_air_provider()
    offer_lookup = GetOfferDetail(search_store, provider, settings.search_cache_ttl_seconds)
    session_factory = get_session_factory()

    order_id: UUID | None = None
    try:
        async with lifespan(app):
            task_queue = _CapturingTaskQueue()
            app.state.task_queue = task_queue

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. логин
                resp = await client.post(
                    "/travel/auth/agent/login", json={"login": login, "password": password}
                )
                assert resp.status_code == 200
                token = resp.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                resp = await client.get("/travel/auth/agent/me", headers=headers)
                assert resp.status_code == 200
                assert resp.json()["id"] == str(agent_id)

                # 2. поиск локаций
                resp = await client.get(
                    "/travel/avia/locations", params={"query": "ALA"}, headers=headers
                )
                assert resp.status_code == 200
                assert any(loc["iata_code"] == "ALA" for loc in resp.json())

                # 3. старт поиска офферов
                departure_date = (date.today() + timedelta(days=30)).isoformat()
                resp = await client.post(
                    "/travel/avia/offers",
                    headers=headers,
                    json={
                        "origin": "ALA",
                        "destination": "IST",
                        "departure_date": departure_date,
                        "passengers": {"adults": 1},
                        "cabin": "economy",
                    },
                )
                assert resp.status_code == 202
                search_id = resp.json()["search_id"]
                assert resp.json()["status"] == "pending"
                assert task_queue.last is not None
                assert str(task_queue.last["search_id"]) == search_id

                # Нет живого воркера в тесте — обрабатываем задачу поиска напрямую.
                captured = task_queue.last
                await process_message(
                    {
                        "search_id": str(captured["search_id"]),
                        "agent_id": str(captured["agent_id"]),
                        "params": to_jsonable(captured["params"]),
                    },
                    search_store,
                    provider,
                    settings.search_cache_ttl_seconds,
                )

                # 4. поллинг результата
                resp = await client.get(f"/travel/avia/offers/search/{search_id}", headers=headers)
                assert resp.status_code == 200
                search_data = resp.json()
                assert search_data["status"] == "done"
                assert len(search_data["offers"]) > 0
                offer_id = search_data["offers"][0]["offer_id"]

                # 5. детали оффера
                resp = await client.get(f"/travel/avia/offers/{offer_id}", headers=headers)
                assert resp.status_code == 200
                offer_detail = resp.json()
                fare_family = offer_detail["fare_families"][0]["code"]

                # 6. создать заказ
                idempotency_key = str(uuid4())
                order_body = {
                    "offer_id": offer_id,
                    "fare_family": fare_family,
                    "passengers": [
                        {
                            "type": "ADT",
                            "first_name": "IVAN",
                            "last_name": "IVANOV",
                            "birth_date": "1990-01-01",
                            "gender": "M",
                            "citizenship": "KZ",
                            "document_number": "N12345678",
                            "document_expiry": "2099-01-01",
                        }
                    ],
                    "contact": {"email": "e2e@example.com", "phone": "+77001234567"},
                }
                resp = await client.post(
                    "/travel/avia/orders",
                    headers={**headers, "Idempotency-Key": idempotency_key},
                    json=order_body,
                )
                assert resp.status_code == 201
                order_data = resp.json()
                order_id = UUID(order_data["id"])
                assert order_data["status"] == "BOOKED"

                # 7. выписка
                resp = await client.post(f"/travel/avia/orders/{order_id}/issue", headers=headers)
                assert resp.status_code == 200
                assert resp.json()["status"] == "ISSUED"
                assert len(resp.json()["ticket_numbers"]) == 1

                # Билет ещё не готов: событие лежит в outbox, воркера в тесте нет.
                resp = await client.get(f"/travel/avia/orders/{order_id}/ticket", headers=headers)
                assert resp.status_code == 409
                assert resp.json()["error"]["code"] == "ticket_not_ready"

                # Нет живого воркера — прогоняем outbox relay и консьюмер ticket.generate напрямую.
                published: list[tuple[str, dict[str, Any]]] = []

                async def _publish(event_type: str, payload: dict[str, Any]) -> None:
                    published.append((event_type, payload))

                relayed = await relay_once(session_factory, _publish, batch_size=50)
                assert relayed >= 1
                for event_type, payload in published:
                    if event_type == "ticket.generate":
                        await process_ticket_generate(payload, session_factory, offer_lookup)

                # 8. скачать билет
                resp = await client.get(f"/travel/avia/orders/{order_id}/ticket", headers=headers)
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "application/pdf"
                assert resp.content.startswith(b"%PDF")
                assert str(order_id).encode() in resp.content

        async with session_factory() as session:
            model = await session.get(OrderModel, order_id)
            assert model is not None
            assert model.status == OrderStatus.ISSUED.value
    finally:
        await _cleanup(agent_id, order_id)
