"""Консьюмер ticket.generate: собирает PDF билета и сохраняет его идемпотентно (SPEC §11)."""

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.offers import GetOfferDetail
from app.infrastructure.db.order_repository import SqlOrderRepository
from app.infrastructure.db.ticket_repository import SqlTicketRepository
from app.infrastructure.ticketing.pdf import generate_ticket_pdf

logger = logging.getLogger(__name__)


async def process_ticket_generate(
    payload: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    offer_lookup: GetOfferDetail,
) -> None:
    order_id = UUID(payload["order_id"])

    async with session_factory() as session:
        tickets = SqlTicketRepository(session)
        if await tickets.exists(order_id):
            return  # идемпотентность: билет уже сгенерирован предыдущим сообщением

        order = await SqlOrderRepository(session).get(order_id)
        if order is None:
            logger.warning("Заказ %s не найден для генерации билета", order_id)
            return

        offer_detail = await offer_lookup.execute(order.offer_id)
        fare = next((f for f in offer_detail.fare_families if f.code == order.fare_family), None)
        pdf_bytes = await asyncio.to_thread(generate_ticket_pdf, order, offer_detail.offer, fare)

        try:
            await tickets.save(order_id, pdf_bytes)
            await session.commit()
        except IntegrityError:
            # Конкурентное сообщение по тому же заказу уже создало билет — не дубль.
            await session.rollback()
