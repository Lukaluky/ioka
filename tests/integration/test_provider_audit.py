from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.domain.errors import ProviderError, ProviderTimeout
from app.domain.search import PassengerCounts, SearchParams
from app.infrastructure.db.models import ProviderRequestModel
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.providers.auditing_air_provider import AuditingAirProvider
from app.infrastructure.providers.mock_air_provider import MockAirProvider, MockProviderConfig


def _params() -> SearchParams:
    return SearchParams(
        origin="ALA",
        destination="IST",
        departure_date=date(2026, 11, 20),
        return_date=None,
        passengers=PassengerCounts(adults=1),
        cabin="economy",
        currency="USD",
    )


async def _latest_rows(operation: str, limit: int = 1) -> list[ProviderRequestModel]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(ProviderRequestModel)
            .where(ProviderRequestModel.operation == operation)
            .order_by(ProviderRequestModel.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _delete_rows(rows: list[ProviderRequestModel]) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        for row in rows:
            obj = await session.get(ProviderRequestModel, row.id)
            if obj is not None:
                await session.delete(obj)
        await session.commit()


async def test_successful_search_is_audited() -> None:
    config = MockProviderConfig(
        delay_min_seconds=0,
        delay_max_seconds=0,
        failure_rate=0.0,
        timeout_rate=0.0,
        timeout_seconds=5,
    )
    provider = AuditingAirProvider(
        MockAirProvider(config), get_session_factory(), timeout_seconds=5, provider_name="mock"
    )
    search_id = uuid4()

    offers = await provider.search(_params(), search_id=search_id)
    assert len(offers) > 0

    rows = await _latest_rows("search")
    try:
        assert rows[0].success is True
        assert rows[0].provider == "mock"
        assert rows[0].search_id == search_id
        assert rows[0].response is not None
    finally:
        await _delete_rows(rows)


async def test_provider_failure_is_audited_and_reraised() -> None:
    config = MockProviderConfig(
        delay_min_seconds=0,
        delay_max_seconds=0,
        failure_rate=1.0,
        timeout_rate=0.0,
        timeout_seconds=5,
    )
    provider = AuditingAirProvider(
        MockAirProvider(config), get_session_factory(), timeout_seconds=5, provider_name="mock"
    )

    with pytest.raises(ProviderError):
        await provider.search(_params())

    rows = await _latest_rows("search")
    try:
        assert rows[0].success is False
        assert rows[0].error is not None
    finally:
        await _delete_rows(rows)


async def test_provider_timeout_is_audited_and_converted() -> None:
    config = MockProviderConfig(
        delay_min_seconds=0,
        delay_max_seconds=0,
        failure_rate=0.0,
        timeout_rate=1.0,
        timeout_seconds=0.05,
    )
    provider = AuditingAirProvider(
        MockAirProvider(config), get_session_factory(), timeout_seconds=0.05, provider_name="mock"
    )

    with pytest.raises(ProviderTimeout):
        await provider.search(_params())

    rows = await _latest_rows("search")
    try:
        assert rows[0].success is False
        assert rows[0].error == "provider_timeout"
    finally:
        await _delete_rows(rows)
