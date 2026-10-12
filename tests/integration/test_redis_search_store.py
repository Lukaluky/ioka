from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment
from app.domain.search import SearchResult, SearchStatus
from app.infrastructure.redis_client import get_redis_client
from app.infrastructure.redis_store import RedisSearchStore


def _sample_offer() -> Offer:
    segment = Segment(
        flight_number="KC123",
        airline="KC",
        origin="ALA",
        destination="IST",
        departure_utc=datetime(2027, 1, 1, 10, 0, tzinfo=UTC),
        departure_local=datetime(2027, 1, 1, 16, 0, tzinfo=UTC),
        arrival_utc=datetime(2027, 1, 1, 14, 0, tzinfo=UTC),
        arrival_local=datetime(2027, 1, 1, 17, 0, tzinfo=UTC),
        duration_minutes=240,
    )
    return Offer(
        offer_id=uuid4(),
        airline="KC",
        segments=[segment],
        stops=0,
        cabin="economy",
        min_price=Money(Decimal("123.45"), "USD"),
    )


async def test_save_and_get_search_result_roundtrip() -> None:
    store = RedisSearchStore(get_redis_client(), search_ttl_seconds=30)
    offer = _sample_offer()
    result = SearchResult(
        search_id=uuid4(), agent_id=uuid4(), status=SearchStatus.DONE, offers=[offer]
    )

    await store.save(result)
    loaded = await store.get(result.search_id)

    assert loaded is not None
    assert loaded.status == SearchStatus.DONE
    assert loaded.offers[0].offer_id == offer.offer_id
    assert loaded.offers[0].min_price.amount == offer.min_price.amount
    assert loaded.offers[0].segments[0].departure_utc == offer.segments[0].departure_utc


async def test_offer_detail_roundtrip() -> None:
    store = RedisSearchStore(get_redis_client(), search_ttl_seconds=30)
    offer = _sample_offer()
    detail = OfferDetail(
        offer=offer,
        fare_families=[
            FareFamily(
                code="LIGHT",
                name="Light",
                price=Money(Decimal("100"), "USD"),
                baggage_kg=0,
                carry_on=True,
                refundable=False,
                exchangeable=False,
            )
        ],
    )

    await store.save_offer_detail(detail, ttl_seconds=30)
    loaded = await store.get_offer_detail(offer.offer_id)

    assert loaded is not None
    assert loaded.fare_families[0].code == "LIGHT"
    assert loaded.offer.min_price.currency == "USD"


async def test_cache_offers_roundtrip() -> None:
    store = RedisSearchStore(get_redis_client(), search_ttl_seconds=30)
    offer = _sample_offer()

    await store.cache_offers("test-cache-key", [offer], ttl_seconds=30)
    loaded = await store.get_cached_offers("test-cache-key")

    assert loaded is not None
    assert loaded[0].offer_id == offer.offer_id


async def test_get_missing_search_returns_none() -> None:
    store = RedisSearchStore(get_redis_client(), search_ttl_seconds=30)

    assert await store.get(uuid4()) is None
