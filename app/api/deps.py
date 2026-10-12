from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth import GetCurrentAgent
from app.application.offers import GetOfferDetail
from app.config import get_settings
from app.domain.agent import Agent
from app.domain.errors import InvalidToken
from app.infrastructure.db.repositories import SqlAgentRepository
from app.infrastructure.db.session import get_session
from app.infrastructure.db.unit_of_work import SqlUnitOfWork
from app.infrastructure.providers.auditing_air_provider import AuditingAirProvider
from app.infrastructure.providers.factory import build_air_provider
from app.infrastructure.rabbitmq import RabbitMqTaskQueue
from app.infrastructure.redis_client import get_redis_client
from app.infrastructure.redis_store import RedisSearchStore
from app.infrastructure.security import BcryptPasswordHasher, JwtTokenService

DbSession = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False: без заголовка Authorization нужен наш формат ошибки (401 not_authenticated),
# а не стандартный ответ HTTPBearer.
_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_password_hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher()


@lru_cache
def get_token_service() -> JwtTokenService:
    settings = get_settings()
    return JwtTokenService(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        ttl_minutes=settings.jwt_ttl_minutes,
    )


async def get_current_agent(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: DbSession,
    tokens: Annotated[JwtTokenService, Depends(get_token_service)],
) -> Agent:
    if credentials is None:
        raise InvalidToken
    use_case = GetCurrentAgent(SqlAgentRepository(session), tokens)
    return await use_case.execute(credentials.credentials)


CurrentAgent = Annotated[Agent, Depends(get_current_agent)]


@lru_cache
def get_search_store() -> RedisSearchStore:
    return RedisSearchStore(get_redis_client(), get_settings().search_ttl_seconds)


def get_task_queue(request: Request) -> RabbitMqTaskQueue:
    # Создаётся один раз в lifespan (app/main.py) и живёт вместе с приложением.
    return request.app.state.task_queue  # type: ignore[no-any-return]


SearchStoreDep = Annotated[RedisSearchStore, Depends(get_search_store)]
TaskQueueDep = Annotated[RabbitMqTaskQueue, Depends(get_task_queue)]


@lru_cache
def get_air_provider() -> AuditingAirProvider:
    return build_air_provider()


AirProviderDep = Annotated[AuditingAirProvider, Depends(get_air_provider)]


def get_offer_lookup(search_store: SearchStoreDep, provider: AirProviderDep) -> GetOfferDetail:
    return GetOfferDetail(search_store, provider, get_settings().search_cache_ttl_seconds)


OfferLookupDep = Annotated[GetOfferDetail, Depends(get_offer_lookup)]


def get_unit_of_work(session: DbSession) -> SqlUnitOfWork:
    return SqlUnitOfWork(session)


UnitOfWorkDep = Annotated[SqlUnitOfWork, Depends(get_unit_of_work)]
