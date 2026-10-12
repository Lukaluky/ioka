from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import register_middleware
from app.api.routers.auth import router as auth_router
from app.api.routers.locations import router as locations_router
from app.api.routers.offers import router as offers_router
from app.api.routers.orders import router as orders_router
from app.config import get_settings
from app.infrastructure.rabbitmq import (
    SEARCH_REQUESTED_QUEUE,
    RabbitMqTaskQueue,
    connect_with_retry,
)
from app.logging_config import configure_logging

API_DESCRIPTION = """
Сервис бронирования авиабилетов для турагентов: логин агента, поиск IATA-кодов,
асинхронный поиск офферов с поллингом, бронь, выписка со списанием баланса, PDF билета.

Все эндпоинты, кроме `/travel/auth/agent/login` и `/health`, требуют
`Authorization: Bearer <token>`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    connection = await connect_with_retry(get_settings().rabbitmq_url)
    channel = await connection.channel()
    await channel.declare_queue(SEARCH_REQUESTED_QUEUE, durable=True)
    app.state.task_queue = RabbitMqTaskQueue(channel)
    try:
        yield
    finally:
        await connection.close()


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Travel Booking API",
        description=API_DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    register_middleware(app)
    app.include_router(auth_router)
    app.include_router(locations_router)
    app.include_router(offers_router)
    app.include_router(orders_router)

    @app.get("/health", tags=["system"], summary="Liveness-проверка")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
