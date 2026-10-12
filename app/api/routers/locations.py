from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAgent, DbSession
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.locations import LocationResponse
from app.application.locations import SearchLocations
from app.infrastructure.db.repositories import SqlLocationRepository

router = APIRouter(prefix="/travel/avia", tags=["locations"])


@router.get(
    "/locations",
    response_model=list[LocationResponse],
    summary="Поиск IATA-кодов",
    description="Ранжирование: точный код -> префикс города/названия -> подстрока, "
    "регистр не важен (SPEC §4).",
    responses={401: {"model": ErrorResponse, "description": "not_authenticated"}},
)
async def search_locations(
    agent: CurrentAgent,
    session: DbSession,
    query: Annotated[str, Query(min_length=2, description="Минимум 2 символа")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[LocationResponse]:
    use_case = SearchLocations(SqlLocationRepository(session))
    locations = await use_case.execute(query, limit)
    return [LocationResponse(**vars(location)) for location in locations]
