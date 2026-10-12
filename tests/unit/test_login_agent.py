from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.auth import LoginAgent
from app.domain.agent import Agent
from app.domain.errors import AgentInactive, InvalidCredentials
from app.infrastructure.security import JwtTokenService
from tests.unit.fakes import FakeAgentRepository, FakePasswordHasher


def make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "login": "agent1",
        "password_hash": "hashed:secret",
        "name": "Agent",
        "balance": Decimal("100"),
        "currency": "USD",
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def tokens() -> JwtTokenService:
    return JwtTokenService(secret="test-secret", algorithm="HS256", ttl_minutes=60)


async def test_login_success(tokens: JwtTokenService) -> None:
    agent = make_agent()
    use_case = LoginAgent(FakeAgentRepository([agent]), FakePasswordHasher(), tokens)

    token = await use_case.execute("agent1", "secret")

    assert tokens.decode_access_token(token) == agent.id


async def test_login_wrong_password(tokens: JwtTokenService) -> None:
    agent = make_agent()
    use_case = LoginAgent(FakeAgentRepository([agent]), FakePasswordHasher(), tokens)

    with pytest.raises(InvalidCredentials):
        await use_case.execute("agent1", "wrong-password")


async def test_login_unknown_login(tokens: JwtTokenService) -> None:
    use_case = LoginAgent(FakeAgentRepository([]), FakePasswordHasher(), tokens)

    with pytest.raises(InvalidCredentials):
        await use_case.execute("ghost", "whatever")


async def test_login_inactive_agent(tokens: JwtTokenService) -> None:
    agent = make_agent(is_active=False)
    use_case = LoginAgent(FakeAgentRepository([agent]), FakePasswordHasher(), tokens)

    with pytest.raises(AgentInactive):
        await use_case.execute("agent1", "secret")
