from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.search import StartSearch
from app.domain.errors import LocationNotFound, SearchValidationError
from app.domain.location import Location
from app.domain.money import Money
from app.domain.offer import Offer
from app.domain.search import PassengerCounts, SearchParams, SearchStatus


class FakeLocationRepository:
    def __init__(self, codes: set[str]) -> None:
        self._codes = codes

    async def search(self, query: str, limit: int) -> list[Location]:
        return []

    async def get_by_code(self, iata_code: str) -> Location | None:
        code = iata_code.upper()
        if code not in self._codes:
            return None
        return Location(iata_code=code, name="X", city="X", country_code="XX", type="large_airport")


class FakeSearchStore:
    def __init__(self) -> None:
        self.saved: list = []
        self.cache: dict[str, list[Offer]] = {}

    async def save(self, result) -> None:
        self.saved.append(result)

    async def get(self, search_id: UUID):
        for result in reversed(self.saved):
            if result.search_id == search_id:
                return result
        return None

    async def get_cached_offers(self, cache_key: str) -> list[Offer] | None:
        return self.cache.get(cache_key)

    async def cache_offers(self, cache_key: str, offers: list[Offer], ttl_seconds: int) -> None:
        self.cache[cache_key] = offers

    async def save_offer_detail(self, detail, ttl_seconds: int) -> None:
        pass

    async def get_offer_detail(self, offer_id: UUID):
        return None


class FakeTaskQueue:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish_search_requested(self, search_id: UUID, agent_id: UUID, params) -> None:
        self.published.append((search_id, agent_id, params))


def _params(**overrides: object) -> SearchParams:
    base: dict[str, object] = {
        "origin": "ALA",
        "destination": "IST",
        "departure_date": date(2027, 1, 1),
        "return_date": None,
        "passengers": PassengerCounts(adults=1),
        "cabin": "economy",
        "currency": "USD",
    }
    base.update(overrides)
    return SearchParams(**base)  # type: ignore[arg-type]


def _make_use_case(
    codes: set[str] = frozenset({"ALA", "IST"}),
) -> tuple[StartSearch, FakeSearchStore, FakeTaskQueue]:
    store = FakeSearchStore()
    queue = FakeTaskQueue()
    use_case = StartSearch(
        FakeLocationRepository(set(codes)),
        store,
        queue,
        search_ttl_seconds=900,
        cache_ttl_seconds=300,
    )
    return use_case, store, queue


async def test_start_search_publishes_task_for_new_params() -> None:
    use_case, store, queue = _make_use_case()

    result = await use_case.execute(uuid4(), _params())

    assert result.status == SearchStatus.PENDING
    assert len(queue.published) == 1
    assert store.saved[-1].status == SearchStatus.PENDING


async def test_cache_hit_skips_queue_and_returns_done() -> None:
    use_case, store, queue = _make_use_case()
    params = _params()
    from app.domain.search import compute_cache_key

    cached_offer = Offer(
        offer_id=uuid4(),
        airline="KC",
        segments=[],
        stops=0,
        cabin="economy",
        min_price=Money(Decimal("100"), "USD"),
    )
    store.cache[compute_cache_key(params)] = [cached_offer]

    result = await use_case.execute(uuid4(), params)

    assert result.status == SearchStatus.DONE
    assert result.offers == [cached_offer]
    assert queue.published == []


async def test_unknown_origin_raises_location_not_found() -> None:
    use_case, _, _ = _make_use_case(codes={"IST"})

    with pytest.raises(LocationNotFound):
        await use_case.execute(uuid4(), _params())


async def test_same_origin_and_destination_raises_validation_error() -> None:
    use_case, _, _ = _make_use_case(codes={"ALA"})

    with pytest.raises(SearchValidationError):
        await use_case.execute(uuid4(), _params(destination="ALA"))


async def test_departure_in_past_raises_validation_error() -> None:
    use_case, _, _ = _make_use_case()

    with pytest.raises(SearchValidationError):
        await use_case.execute(uuid4(), _params(departure_date=date(2020, 1, 1)))


async def test_return_before_departure_raises_validation_error() -> None:
    use_case, _, _ = _make_use_case()

    with pytest.raises(SearchValidationError):
        await use_case.execute(
            uuid4(), _params(departure_date=date(2027, 1, 10), return_date=date(2027, 1, 5))
        )


async def test_too_many_infants_raises_validation_error() -> None:
    use_case, _, _ = _make_use_case()

    with pytest.raises(SearchValidationError):
        await use_case.execute(uuid4(), _params(passengers=PassengerCounts(adults=1, infants=2)))


async def test_too_many_passengers_raises_validation_error() -> None:
    use_case, _, _ = _make_use_case()

    with pytest.raises(SearchValidationError):
        await use_case.execute(uuid4(), _params(passengers=PassengerCounts(adults=9, children=1)))
