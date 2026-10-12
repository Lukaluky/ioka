import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from app.domain.search import SearchParams
from app.infrastructure.json_utils import to_jsonable

SEARCH_REQUESTED_QUEUE = "search.requested"
TICKET_GENERATE_QUEUE = "ticket.generate"

logger = logging.getLogger(__name__)


async def connect_with_retry(
    url: str, *, attempts: int = 10, delay_seconds: float = 2.0
) -> AbstractRobustConnection:
    """RabbitMQ healthcheck иногда зелёный на пару секунд раньше, чем AMQP-порт готов принимать
    соединения — поэтому на старте пытаемся подключиться несколько раз, а не один."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await aio_pika.connect_robust(url)
        except (ConnectionError, OSError) as exc:
            last_error = exc
            logger.warning(
                "Попытка %s/%s подключения к RabbitMQ не удалась: %s", attempt, attempts, exc
            )
            await asyncio.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


class RabbitMqTaskQueue:
    def __init__(self, channel: AbstractChannel) -> None:
        self._channel = channel

    async def publish_search_requested(
        self, search_id: UUID, agent_id: UUID, params: SearchParams
    ) -> None:
        payload = {
            "search_id": str(search_id),
            "agent_id": str(agent_id),
            "params": to_jsonable(params),
        }
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._channel.default_exchange.publish(message, routing_key=SEARCH_REQUESTED_QUEUE)


async def publish_event(channel: AbstractChannel, event_type: str, payload: dict[str, Any]) -> None:
    """Публикация outbox-события: routing_key = event_type = имя очереди (SPEC §11)."""
    message = aio_pika.Message(
        body=json.dumps(payload).encode(),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await channel.default_exchange.publish(message, routing_key=event_type)
