from app.application.ports import AgentRepository, PasswordHasher, TokenService
from app.domain.agent import Agent
from app.domain.errors import AgentInactive, InvalidCredentials, InvalidToken


class LoginAgent:
    def __init__(
        self,
        agents: AgentRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
    ) -> None:
        self._agents = agents
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, login: str, password: str) -> str:
        agent = await self._agents.get_by_login(login)
        password_hash = agent.password_hash if agent is not None else self._hasher.dummy_hash
        is_valid = await self._hasher.verify(password, password_hash)
        if agent is None or not is_valid:
            raise InvalidCredentials
        if not agent.is_active:
            raise AgentInactive
        return self._tokens.create_access_token(agent.id)


class GetCurrentAgent:
    def __init__(self, agents: AgentRepository, tokens: TokenService) -> None:
        self._agents = agents
        self._tokens = tokens

    async def execute(self, token: str) -> Agent:
        agent_id = self._tokens.decode_access_token(token)
        agent = await self._agents.get_by_id(agent_id)
        if agent is None:
            raise InvalidToken
        if not agent.is_active:
            raise AgentInactive
        return agent
