import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

logger = logging.getLogger("app.request")


async def _request_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    started = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    # Секреты, токены и персональные данные пассажиров сюда не попадают — логируется
    # только техническая информация о запросе.
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


def register_middleware(app: FastAPI) -> None:
    app.middleware("http")(_request_logging_middleware)
