from uuid import UUID

from app.domain.agent import Agent


class FakeAgentRepository:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        self._by_login = {a.login: a for a in agents or []}
        self._by_id = {a.id: a for a in agents or []}

    async def get_by_login(self, login: str) -> Agent | None:
        return self._by_login.get(login)

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        return self._by_id.get(agent_id)


class FakePasswordHasher:
    dummy_hash = "dummy"

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, password_hash: str) -> bool:
        if password_hash == self.dummy_hash:
            return False
        return password_hash == f"hashed:{password}"
