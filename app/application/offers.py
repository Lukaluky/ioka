from uuid import UUID

from app.application.ports import AirProvider, SearchStore
from app.domain.offer import OfferDetail


class GetOfferDetail:
    def __init__(
        self, search_store: SearchStore, provider: AirProvider, cache_ttl_seconds: int
    ) -> None:
        self._search_store = search_store
        self._provider = provider
        self._cache_ttl_seconds = cache_ttl_seconds

    async def execute(self, offer_id: UUID) -> OfferDetail:
        detail = await self._search_store.get_offer_detail(offer_id)
        if detail is not None:
            return detail
        # SPEC §7: оффер истёк в Redis — как резервный сценарий идём в провайдер напрямую.
        detail = await self._provider.get_offer(offer_id)
        await self._search_store.save_offer_detail(detail, ttl_seconds=self._cache_ttl_seconds)
        return detail
