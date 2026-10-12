"""Outbox relay: раз в секунду публикует неопубликованные события в RabbitMQ (SPEC §11)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.ledger_repository import SqlOutboxRepository

logger = logging.getLogger(__name__)

PublishFn = Callable[[str, dict[str, Any]], Awaitable[None]]


async def relay_once(
    session_factory: async_sessionmaker[AsyncSession], publish: PublishFn, batch_size: int = 10
) -> int:
    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        # FOR UPDATE SKIP LOCKED: несколько воркеров могут гонять relay без дублирования публикации.
        events = await repo.fetch_unpublished_for_update(batch_size)
        for event in events:
            await publish(event.event_type, event.payload)
            await repo.mark_published(event.id)
        await session.commit()
        return len(events)


async def run_outbox_relay(
    session_factory: async_sessionmaker[AsyncSession],
    publish: PublishFn,
    interval_seconds: float = 1.0,
) -> None:
    while True:
        try:
            await relay_once(session_factory, publish)
        except Exception:
            logger.exception("Ошибка outbox relay")
        await asyncio.sleep(interval_seconds)
