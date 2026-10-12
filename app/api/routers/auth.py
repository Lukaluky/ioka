from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentAgent, DbSession, get_password_hasher, get_token_service
from app.api.schemas.auth import AgentMeResponse, LoginRequest, LoginResponse
from app.api.schemas.errors import ErrorResponse
from app.application.auth import LoginAgent
from app.infrastructure.db.repositories import SqlAgentRepository
from app.infrastructure.security import BcryptPasswordHasher, JwtTokenService

router = APIRouter(prefix="/travel/auth/agent", tags=["auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Логин агента",
    description="Возвращает JWT (Bearer). Неверный логин или пароль дают одинаковый ответ 401, "
    "чтобы нельзя было перебором угадать существующие логины.",
    responses={
        401: {"model": ErrorResponse, "description": "invalid_credentials"},
        403: {"model": ErrorResponse, "description": "agent_inactive"},
    },
)
async def login(
    payload: LoginRequest,
    session: DbSession,
    hasher: Annotated[BcryptPasswordHasher, Depends(get_password_hasher)],
    tokens: Annotated[JwtTokenService, Depends(get_token_service)],
) -> LoginResponse:
    use_case = LoginAgent(SqlAgentRepository(session), hasher, tokens)
    access_token = await use_case.execute(payload.login, payload.password)
    return LoginResponse(access_token=access_token)


@router.get(
    "/me",
    response_model=AgentMeResponse,
    summary="Текущий агент",
    description="Данные и баланс агента, которому принадлежит переданный токен.",
    responses={401: {"model": ErrorResponse, "description": "not_authenticated"}},
)
async def me(agent: CurrentAgent) -> AgentMeResponse:
    return AgentMeResponse(
        id=agent.id,
        login=agent.login,
        name=agent.name,
        balance=agent.balance,
        currency=agent.currency,
        is_active=agent.is_active,
    )
