"""Воркер: search.requested, ticket.generate и outbox relay на одном RabbitMQ-соединении."""

import asyncio
import json
import logging
from datetime import date
from typing import Any
from uuid import UUID

from aio_pika.abc import AbstractIncomingMessage

from app.application.offers import GetOfferDetail
from app.application.ports import AirProvider, SearchStore
from app.config import get_settings
from app.domain.errors import ProviderError, ProviderTimeout
from app.domain.search import (
    PassengerCounts,
    SearchParams,
    SearchResult,
    SearchStatus,
    compute_cache_key,
)
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.providers.factory import build_air_provider
from app.infrastructure.rabbitmq import (
    SEARCH_REQUESTED_QUEUE,
    TICKET_GENERATE_QUEUE,
    connect_with_retry,
    publish_event,
)
from app.infrastructure.redis_client import get_redis_client
from app.infrastructure.redis_store import RedisSearchStore
from app.logging_config import configure_logging
from app.worker.outbox_relay import run_outbox_relay
from app.worker.ticket_consumer import process_ticket_generate

logger = logging.getLogger(__name__)


def _params_from_payload(data: dict[str, Any]) -> SearchParams:
    passengers = data["passengers"]
    return SearchParams(
        origin=data["origin"],
        destination=data["destination"],
        departure_date=date.fromisoformat(data["departure_date"]),
        return_date=date.fromisoformat(data["return_date"]) if data.get("return_date") else None,
        passengers=PassengerCounts(
            adults=passengers["adults"],
            children=passengers["children"],
            infants=passengers["infants"],
        ),
        cabin=data["cabin"],
        currency=data["currency"],
    )


async def process_message(
    payload: dict[str, Any],
    search_store: SearchStore,
    provider: AirProvider,
    cache_ttl_seconds: int,
) -> None:
    search_id = UUID(payload["search_id"])
    agent_id = UUID(payload["agent_id"])
    params = _params_from_payload(payload["params"])

    try:
        offers = await provider.search(params)
    except ProviderTimeout:
        await search_store.save(
            SearchResult(search_id, agent_id, SearchStatus.FAILED, reason="provider_timeout")
        )
        return
    except ProviderError:
        await search_store.save(
            SearchResult(search_id, agent_id, SearchStatus.FAILED, reason="provider_error")
        )
        return
    except Exception:
        logger.exception("Неожиданная ошибка при поиске %s", search_id)
        await search_store.save(
            SearchResult(search_id, agent_id, SearchStatus.FAILED, reason="provider_error")
        )
        return

    # Детали (fare families) тянем сразу и кладём в offer:{id}, чтобы GET /offers/{id}
    # (этап 4) обычно не ходил в провайдер повторно — только как резервный сценарий.
    for offer in offers:
        try:
            detail = await provider.get_offer(offer.offer_id)
        except Exception:
            logger.warning("Не удалось получить детали оффера %s", offer.offer_id)
            continue
        await search_store.save_offer_detail(detail, ttl_seconds=cache_ttl_seconds)

    await search_store.cache_offers(
        compute_cache_key(params), offers, ttl_seconds=cache_ttl_seconds
    )
    await search_store.save(SearchResult(search_id, agent_id, SearchStatus.DONE, offers=offers))


async def main() -> None:
    configure_logging()
    settings = get_settings()
    search_store = RedisSearchStore(get_redis_client(), settings.search_ttl_seconds)
    provider = build_air_provider()
    session_factory = get_session_factory()
    offer_lookup = GetOfferDetail(search_store, provider, settings.search_cache_ttl_seconds)

    connection = await connect_with_retry(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        search_queue = await channel.declare_queue(SEARCH_REQUESTED_QUEUE, durable=True)
        ticket_queue = await channel.declare_queue(TICKET_GENERATE_QUEUE, durable=True)
        logger.info("Воркер слушает очереди %s, %s", SEARCH_REQUESTED_QUEUE, TICKET_GENERATE_QUEUE)

        async def _on_search_message(message: AbstractIncomingMessage) -> None:
            async with message.process():
                payload = json.loads(message.body)
                try:
                    await process_message(
                        payload, search_store, provider, settings.search_cache_ttl_seconds
                    )
                except Exception:
                    logger.exception(
                        "Необработанная ошибка при обработке поиска %s", payload.get("search_id")
                    )

        async def _on_ticket_message(message: AbstractIncomingMessage) -> None:
            async with message.process():
                payload = json.loads(message.body)
                try:
                    await process_ticket_generate(payload, session_factory, offer_lookup)
                except Exception:
                    logger.exception(
                        "Необработанная ошибка при генерации билета %s", payload.get("order_id")
                    )

        await search_queue.consume(_on_search_message)
        await ticket_queue.consume(_on_ticket_message)

        async def _publish(event_type: str, event_payload: dict[str, Any]) -> None:
            await publish_event(channel, event_type, event_payload)

        relay_task = asyncio.create_task(run_outbox_relay(session_factory, _publish))
        try:
            await asyncio.Future()  # работаем, пока процесс не остановят
        finally:
            relay_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
