from datetime import date
from uuid import uuid4

import pytest

from app.domain.errors import OfferNotFound, ProviderError
from app.domain.search import PassengerCounts, SearchParams
from app.infrastructure.providers.mock_air_provider import MockAirProvider, MockProviderConfig


def _params(departure_date: date = date(2026, 11, 20)) -> SearchParams:
    return SearchParams(
        origin="ALA",
        destination="IST",
        departure_date=departure_date,
        return_date=None,
        passengers=PassengerCounts(adults=1),
        cabin="economy",
        currency="USD",
    )


def _fast_config(**overrides: float) -> MockProviderConfig:
    base: dict[str, float] = {
        "delay_min_seconds": 0.0,
        "delay_max_seconds": 0.0,
        "failure_rate": 0.0,
        "timeout_rate": 0.0,
        "timeout_seconds": 1.0,
    }
    base.update(overrides)
    return MockProviderConfig(**base)  # type: ignore[arg-type]


async def test_search_is_deterministic_for_same_params() -> None:
    offers_a = await MockAirProvider(_fast_config()).search(_params())
    offers_b = await MockAirProvider(_fast_config()).search(_params())

    content_a = [
        (o.airline, o.stops, o.cabin, o.min_price.amount, o.min_price.currency) for o in offers_a
    ]
    content_b = [
        (o.airline, o.stops, o.cabin, o.min_price.amount, o.min_price.currency) for o in offers_b
    ]
    assert content_a == content_b


async def test_search_changes_with_different_date() -> None:
    offers_a = await MockAirProvider(_fast_config()).search(_params())
    offers_b = await MockAirProvider(_fast_config()).search(_params(date(2026, 12, 1)))

    content_a = [(o.airline, o.stops) for o in offers_a]
    content_b = [(o.airline, o.stops) for o in offers_b]
    assert content_a != content_b


async def test_get_offer_returns_fare_families_after_search() -> None:
    provider = MockAirProvider(_fast_config())
    offers = await provider.search(_params())

    detail = await provider.get_offer(offers[0].offer_id)

    assert detail.offer.offer_id == offers[0].offer_id
    assert {fare.code for fare in detail.fare_families} == {"LIGHT", "STANDARD", "FLEX"}


async def test_get_unknown_offer_raises_not_found() -> None:
    provider = MockAirProvider(_fast_config())

    with pytest.raises(OfferNotFound):
        await provider.get_offer(uuid4())


async def test_failure_rate_raises_provider_error() -> None:
    provider = MockAirProvider(_fast_config(failure_rate=1.0))

    with pytest.raises(ProviderError):
        await provider.search(_params())
