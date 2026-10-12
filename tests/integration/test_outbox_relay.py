from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.db.ledger_repository import SqlOutboxRepository
from app.infrastructure.db.models import OutboxModel
from app.infrastructure.db.session import get_session_factory
from app.worker.outbox_relay import relay_once


async def test_relay_once_publishes_and_marks_unpublished_events() -> None:
    session_factory = get_session_factory()
    marker = str(uuid4())

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        await repo.add("ticket.generate", {"order_id": marker})
        await session.commit()

    published: list[tuple[str, dict]] = []

    async def _publish(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    try:
        count = await relay_once(session_factory, _publish, batch_size=50)
        assert count >= 1
        assert ("ticket.generate", {"order_id": marker}) in published

        async with session_factory() as session:
            result = await session.execute(
                select(OutboxModel).where(OutboxModel.payload["order_id"].astext == marker)
            )
            model = result.scalar_one()
            assert model.published is True
    finally:
        async with session_factory() as session:
            result = await session.execute(
                select(OutboxModel).where(OutboxModel.payload["order_id"].astext == marker)
            )
            model = result.scalar_one_or_none()
            if model is not None:
                await session.delete(model)
            await session.commit()


async def test_relay_once_does_not_republish_already_published_events() -> None:
    session_factory = get_session_factory()
    marker = str(uuid4())

    async with session_factory() as session:
        repo = SqlOutboxRepository(session)
        await repo.add("ticket.generate", {"order_id": marker})
        await session.commit()

    async def _noop_publish(event_type: str, payload: dict) -> None:
        pass

    try:
        await relay_once(session_factory, _noop_publish, batch_size=50)

        published_again: list[tuple[str, dict]] = []

        async def _publish(event_type: str, payload: dict) -> None:
            published_again.append((event_type, payload))

        await relay_once(session_factory, _publish, batch_size=50)
        assert published_again == []
    finally:
        async with session_factory() as session:
            result = await session.execute(
                select(OutboxModel).where(OutboxModel.payload["order_id"].astext == marker)
            )
            model = result.scalar_one_or_none()
            if model is not None:
                await session.delete(model)
            await session.commit()
