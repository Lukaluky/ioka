from typing import Any
from uuid import uuid4

from app.domain.search import SearchStatus
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.providers.auditing_air_provider import AuditingAirProvider
from app.infrastructure.providers.mock_air_provider import MockAirProvider, MockProviderConfig
from app.infrastructure.redis_client import get_redis_client
from app.infrastructure.redis_store import RedisSearchStore
from app.worker.main import process_message


def _payload(search_id: object, agent_id: object) -> dict[str, Any]:
    return {
        "search_id": str(search_id),
        "agent_id": str(agent_id),
        "params": {
            "origin": "ALA",
            "destination": "IST",
            "departure_date": "2027-01-01",
            "return_date": None,
            "passengers": {"adults": 1, "children": 0, "infants": 0},
            "cabin": "economy",
            "currency": "USD",
        },
    }


def _store() -> RedisSearchStore:
    return RedisSearchStore(get_redis_client(), search_ttl_seconds=60)


async def test_successful_processing_marks_done() -> None:
    search_id, agent_id = uuid4(), uuid4()
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
    store = _store()

    await process_message(_payload(search_id, agent_id), store, provider, cache_ttl_seconds=60)

    result = await store.get(search_id)
    assert result is not None
    assert result.status == SearchStatus.DONE
    assert len(result.offers) > 0


async def test_provider_timeout_marks_failed() -> None:
    search_id, agent_id = uuid4(), uuid4()
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
    store = _store()

    await process_message(_payload(search_id, agent_id), store, provider, cache_ttl_seconds=60)

    result = await store.get(search_id)
    assert result is not None
    assert result.status == SearchStatus.FAILED
    assert result.reason == "provider_timeout"


async def test_provider_failure_marks_failed() -> None:
    search_id, agent_id = uuid4(), uuid4()
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
    store = _store()

    await process_message(_payload(search_id, agent_id), store, provider, cache_ttl_seconds=60)

    result = await store.get(search_id)
    assert result is not None
    assert result.status == SearchStatus.FAILED
    assert result.reason == "provider_error"
