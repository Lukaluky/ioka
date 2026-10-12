import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports import AirProvider
from app.domain.errors import ProviderTimeout
from app.domain.offer import Offer, OfferDetail
from app.domain.order import Contact, Passenger
from app.domain.search import SearchParams
from app.infrastructure.db.models import ProviderRequestModel
from app.infrastructure.json_utils import mask_sensitive, to_jsonable, truncate_response

_T = TypeVar("_T")


class AuditingAirProvider:
    """Оборачивает любой AirProvider: таймаут из конфига + запись в provider_requests.

    Таймаут и аудит — оба сквозные заботы вокруг вызова провайдера, поэтому живут
    в одном декораторе, а не дублируются в каждом use case.
    """

    def __init__(
        self,
        provider: AirProvider,
        session_factory: async_sessionmaker[AsyncSession],
        timeout_seconds: float,
        provider_name: str = "mock",
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._timeout_seconds = timeout_seconds
        self._provider_name = provider_name

    async def search(self, params: SearchParams, *, search_id: UUID | None = None) -> list[Offer]:
        return await self._call(
            operation="search",
            request_payload=params,
            call=lambda: self._provider.search(params),
            search_id=search_id,
        )

    async def get_offer(self, offer_id: UUID, *, order_id: UUID | None = None) -> OfferDetail:
        return await self._call(
            operation="get_offer",
            request_payload={"offer_id": offer_id},
            call=lambda: self._provider.get_offer(offer_id),
            order_id=order_id,
        )

    async def issue(
        self,
        order_id: UUID,
        offer_id: UUID,
        fare_family: str,
        passengers: list[Passenger],
        contact: Contact,
    ) -> list[str]:
        request_payload = {
            "order_id": order_id,
            "offer_id": offer_id,
            "fare_family": fare_family,
            "passengers": passengers,
            "contact": contact,
        }
        return await self._call(
            operation="issue",
            request_payload=request_payload,
            call=lambda: self._provider.issue(order_id, offer_id, fare_family, passengers, contact),
            order_id=order_id,
        )

    async def _call(
        self,
        *,
        operation: str,
        request_payload: Any,
        call: Callable[[], Awaitable[_T]],
        search_id: UUID | None = None,
        order_id: UUID | None = None,
    ) -> _T:
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(call(), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            await self._write_log(
                operation,
                request_payload,
                None,
                "provider_timeout",
                False,
                started,
                search_id,
                order_id,
            )
            raise ProviderTimeout from exc
        except Exception as exc:
            await self._write_log(
                operation, request_payload, None, str(exc), False, started, search_id, order_id
            )
            raise
        await self._write_log(
            operation, request_payload, result, None, True, started, search_id, order_id
        )
        return result

    async def _write_log(
        self,
        operation: str,
        request_payload: Any,
        response_payload: Any,
        error: str | None,
        success: bool,
        started_at: float,
        search_id: UUID | None,
        order_id: UUID | None,
    ) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        request_json = mask_sensitive(to_jsonable(request_payload))
        response_json = (
            mask_sensitive(truncate_response(to_jsonable(response_payload)))
            if response_payload is not None
            else None
        )
        async with self._session_factory() as session:
            session.add(
                ProviderRequestModel(
                    provider=self._provider_name,
                    operation=operation,
                    request=request_json,
                    response=response_json,
                    error=error,
                    success=success,
                    duration_ms=duration_ms,
                    search_id=search_id,
                    order_id=order_id,
                )
            )
            await session.commit()
