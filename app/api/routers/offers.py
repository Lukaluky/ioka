from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentAgent, DbSession, OfferLookupDep, SearchStoreDep, TaskQueueDep
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.search import (
    FareFamilyResponse,
    OfferDetailResponse,
    OfferResponse,
    SearchAcceptedResponse,
    SearchRequest,
    SearchStatusResponse,
    SegmentResponse,
)
from app.application.search import GetSearchResult, StartSearch
from app.config import get_settings
from app.domain.offer import Offer
from app.domain.search import PassengerCounts, SearchParams
from app.infrastructure.db.repositories import SqlLocationRepository

router = APIRouter(prefix="/travel/avia", tags=["offers"])


def _offer_to_response(offer: Offer) -> OfferResponse:
    return OfferResponse(
        offer_id=offer.offer_id,
        airline=offer.airline,
        segments=[SegmentResponse(**vars(segment)) for segment in offer.segments],
        stops=offer.stops,
        cabin=offer.cabin,
        min_price=offer.min_price.amount,
        currency=offer.min_price.currency,
    )


@router.post(
    "/offers",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SearchAcceptedResponse,
    summary="Запустить асинхронный поиск офферов",
    description="Создаёт search_id и публикует задачу в очередь; результат нужно забирать "
    "поллингом GET /offers/search/{search_id}. Если есть свежий кэш по тем же параметрам, "
    "результат готов сразу (статус done) и провайдер не вызывается.",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "location_not_found"},
        422: {"model": ErrorResponse, "description": "validation_error"},
    },
)
async def start_search(
    payload: SearchRequest,
    agent: CurrentAgent,
    session: DbSession,
    search_store: SearchStoreDep,
    task_queue: TaskQueueDep,
) -> SearchAcceptedResponse:
    settings = get_settings()
    params = SearchParams(
        origin=payload.origin.upper(),
        destination=payload.destination.upper(),
        departure_date=payload.departure_date,
        return_date=payload.return_date,
        passengers=PassengerCounts(
            adults=payload.passengers.adults,
            children=payload.passengers.children,
            infants=payload.passengers.infants,
        ),
        cabin=payload.cabin,
        currency=agent.currency,
    )
    use_case = StartSearch(
        SqlLocationRepository(session),
        search_store,
        task_queue,
        search_ttl_seconds=settings.search_ttl_seconds,
        cache_ttl_seconds=settings.search_cache_ttl_seconds,
    )
    result = await use_case.execute(agent.id, params)
    return SearchAcceptedResponse(search_id=result.search_id, status=result.status.value)


@router.get(
    "/offers/search/{search_id}",
    response_model=SearchStatusResponse,
    summary="Статус асинхронного поиска",
    description="status: pending | done | failed. При failed заполнен reason "
    "(provider_timeout | provider_error).",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "search_not_found"},
    },
)
async def get_search(
    search_id: UUID,
    agent: CurrentAgent,
    search_store: SearchStoreDep,
) -> SearchStatusResponse:
    use_case = GetSearchResult(search_store)
    result = await use_case.execute(agent.id, search_id)
    return SearchStatusResponse(
        search_id=result.search_id,
        status=result.status.value,
        reason=result.reason,
        offers=[_offer_to_response(offer) for offer in result.offers],
    )


@router.get(
    "/offers/{offer_id}",
    response_model=OfferDetailResponse,
    summary="Детали оффера с fare families",
    description="Берётся из Redis; при отсутствии (истёк TTL) запрашивается у провайдера "
    "как резервный сценарий.",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "offer_not_found"},
        502: {"model": ErrorResponse, "description": "provider_error"},
        504: {"model": ErrorResponse, "description": "provider_timeout"},
    },
)
async def get_offer(
    offer_id: UUID,
    agent: CurrentAgent,
    offer_lookup: OfferLookupDep,
) -> OfferDetailResponse:
    detail = await offer_lookup.execute(offer_id)
    return OfferDetailResponse(
        offer=_offer_to_response(detail.offer),
        fare_families=[
            FareFamilyResponse(
                code=fare.code,
                name=fare.name,
                price=fare.price.amount,
                currency=fare.price.currency,
                baggage_kg=fare.baggage_kg,
                carry_on=fare.carry_on,
                refundable=fare.refundable,
                exchangeable=fare.exchangeable,
            )
            for fare in detail.fare_families
        ],
    )
