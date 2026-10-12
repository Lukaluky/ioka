from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import case, func

from app.domain.agent import Agent
from app.domain.location import Location
from app.infrastructure.db.models import AgentModel, LocationModel


class SqlAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_login(self, login: str) -> Agent | None:
        result = await self._session.execute(select(AgentModel).where(AgentModel.login == login))
        model = result.scalar_one_or_none()
        return _agent_to_domain(model) if model is not None else None

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        model = await self._session.get(AgentModel, agent_id)
        return _agent_to_domain(model) if model is not None else None

    async def get_for_update(self, agent_id: UUID) -> Agent | None:
        stmt = select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _agent_to_domain(model) if model is not None else None

    async def update_balance(self, agent_id: UUID, new_balance: Decimal) -> None:
        model = await self._session.get(AgentModel, agent_id)
        if model is None:
            return
        model.balance = new_balance
        await self._session.flush()


def _agent_to_domain(model: AgentModel) -> Agent:
    return Agent(
        id=model.id,
        login=model.login,
        password_hash=model.password_hash,
        name=model.name,
        balance=model.balance,
        currency=model.currency,
        is_active=model.is_active,
        created_at=model.created_at,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlLocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, query: str, limit: int) -> list[Location]:
        normalized = query.strip().lower()
        escaped = _escape_like(normalized)
        code_exact = func.lower(LocationModel.iata_code) == normalized
        city_prefix = func.lower(LocationModel.city).like(f"{escaped}%", escape="\\")
        name_prefix = func.lower(LocationModel.name).like(f"{escaped}%", escape="\\")
        city_substring = func.lower(LocationModel.city).like(f"%{escaped}%", escape="\\")
        name_substring = func.lower(LocationModel.name).like(f"%{escaped}%", escape="\\")

        # Ранжирование по SPEC §4: точный код -> префикс города/названия -> подстрока.
        rank = case(
            (code_exact, 0),
            (city_prefix, 1),
            (name_prefix, 1),
            else_=2,
        )
        stmt = (
            select(LocationModel)
            .where(or_(code_exact, city_substring, name_substring))
            .order_by(rank, LocationModel.city, LocationModel.iata_code)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_location_to_domain(model) for model in result.scalars().all()]

    async def get_by_code(self, iata_code: str) -> Location | None:
        model = await self._session.get(LocationModel, iata_code.strip().upper())
        return _location_to_domain(model) if model is not None else None


def _location_to_domain(model: LocationModel) -> Location:
    return Location(
        iata_code=model.iata_code,
        name=model.name,
        city=model.city,
        country_code=model.country_code,
        type=model.type,
    )
