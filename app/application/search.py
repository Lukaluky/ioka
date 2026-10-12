from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.ports import LocationRepository, SearchStore, TaskQueue
from app.domain.errors import LocationNotFound, SearchNotFound, SearchValidationError
from app.domain.search import SearchParams, SearchResult, SearchStatus, compute_cache_key

MAX_TOTAL_PASSENGERS = 9


class StartSearch:
    def __init__(
        self,
        locations: LocationRepository,
        search_store: SearchStore,
        task_queue: TaskQueue,
        search_ttl_seconds: int,
        cache_ttl_seconds: int,
    ) -> None:
        self._locations = locations
        self._search_store = search_store
        self._task_queue = task_queue
        self._search_ttl_seconds = search_ttl_seconds
        self._cache_ttl_seconds = cache_ttl_seconds

    async def execute(self, agent_id: UUID, params: SearchParams) -> SearchResult:
        await self._validate(params)

        cache_key = compute_cache_key(params)
        cached_offers = await self._search_store.get_cached_offers(cache_key)
        if cached_offers is not None:
            result = SearchResult(
                search_id=uuid4(), agent_id=agent_id, status=SearchStatus.DONE, offers=cached_offers
            )
            await self._search_store.save(result)
            return result

        result = SearchResult(search_id=uuid4(), agent_id=agent_id, status=SearchStatus.PENDING)
        await self._search_store.save(result)
        await self._task_queue.publish_search_requested(result.search_id, agent_id, params)
        return result

    async def _validate(self, params: SearchParams) -> None:
        if params.origin.upper() == params.destination.upper():
            raise SearchValidationError("origin и destination не должны совпадать")
        if await self._locations.get_by_code(params.origin) is None:
            raise LocationNotFound(f"Локация {params.origin} не найдена")
        if await self._locations.get_by_code(params.destination) is None:
            raise LocationNotFound(f"Локация {params.destination} не найдена")

        today = datetime.now(UTC).date()
        if params.departure_date < today:
            raise SearchValidationError("Дата вылета не может быть в прошлом")
        if params.return_date is not None and params.return_date < params.departure_date:
            raise SearchValidationError("Дата обратного вылета раньше даты вылета")

        passengers = params.passengers
        if passengers.adults < 1:
            raise SearchValidationError("Нужен хотя бы один взрослый пассажир")
        if passengers.infants > passengers.adults:
            raise SearchValidationError("Младенцев не может быть больше взрослых")
        if passengers.total > MAX_TOTAL_PASSENGERS:
            raise SearchValidationError(
                f"Слишком много пассажиров (максимум {MAX_TOTAL_PASSENGERS})"
            )


class GetSearchResult:
    def __init__(self, search_store: SearchStore) -> None:
        self._search_store = search_store

    async def execute(self, agent_id: UUID, search_id: UUID) -> SearchResult:
        result = await self._search_store.get(search_id)
        if result is None or result.agent_id != agent_id:
            raise SearchNotFound
        return result
