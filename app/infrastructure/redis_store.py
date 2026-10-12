import json
from uuid import UUID

from redis.asyncio import Redis

from app.domain.offer import Offer, OfferDetail
from app.domain.search import SearchResult, SearchStatus
from app.infrastructure.json_utils import to_jsonable
from app.infrastructure.offer_codec import offer_detail_from_dict, offer_from_dict

_SEARCH_PREFIX = "search:"
_OFFER_PREFIX = "offer:"
_CACHE_PREFIX = "offers_cache:"


class RedisSearchStore:
    def __init__(self, client: Redis, search_ttl_seconds: int) -> None:
        self._client = client
        self._search_ttl_seconds = search_ttl_seconds

    async def save(self, result: SearchResult) -> None:
        payload = {
            "search_id": str(result.search_id),
            "agent_id": str(result.agent_id),
            "status": result.status.value,
            "offers": [to_jsonable(offer) for offer in result.offers],
            "reason": result.reason,
        }
        await self._client.set(
            _SEARCH_PREFIX + str(result.search_id), json.dumps(payload), ex=self._search_ttl_seconds
        )

    async def get(self, search_id: UUID) -> SearchResult | None:
        raw = await self._client.get(_SEARCH_PREFIX + str(search_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return SearchResult(
            search_id=UUID(data["search_id"]),
            agent_id=UUID(data["agent_id"]),
            status=SearchStatus(data["status"]),
            offers=[offer_from_dict(o) for o in data["offers"]],
            reason=data.get("reason"),
        )

    async def get_cached_offers(self, cache_key: str) -> list[Offer] | None:
        raw = await self._client.get(_CACHE_PREFIX + cache_key)
        if raw is None:
            return None
        return [offer_from_dict(o) for o in json.loads(raw)]

    async def cache_offers(self, cache_key: str, offers: list[Offer], ttl_seconds: int) -> None:
        payload = [to_jsonable(offer) for offer in offers]
        await self._client.set(_CACHE_PREFIX + cache_key, json.dumps(payload), ex=ttl_seconds)

    async def save_offer_detail(self, detail: OfferDetail, ttl_seconds: int) -> None:
        key = _OFFER_PREFIX + str(detail.offer.offer_id)
        await self._client.set(key, json.dumps(to_jsonable(detail)), ex=ttl_seconds)

    async def get_offer_detail(self, offer_id: UUID) -> OfferDetail | None:
        raw = await self._client.get(_OFFER_PREFIX + str(offer_id))
        if raw is None:
            return None
        return offer_detail_from_dict(json.loads(raw))
