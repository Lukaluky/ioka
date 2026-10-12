import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from app.domain.errors import InvalidToken


class BcryptPasswordHasher:
    def __init__(self) -> None:
        # Считается один раз при старте приложения, а не на каждый запрос с неизвестным логином.
        self.dummy_hash = bcrypt.hashpw(
            b"dummy-password-for-timing-safety", bcrypt.gensalt()
        ).decode()

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hash_sync, password)

    async def verify(self, password: str, password_hash: str) -> bool:
        return await asyncio.to_thread(self._verify_sync, password, password_hash)

    @staticmethod
    def _hash_sync(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def _verify_sync(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except ValueError:
            return False


class JwtTokenService:
    def __init__(self, secret: str, algorithm: str, ttl_minutes: int) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._ttl = timedelta(minutes=ttl_minutes)

    def create_access_token(self, agent_id: UUID) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(agent_id),
            "type": "access",
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_access_token(self, token: str) -> UUID:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise InvalidToken from exc
        if payload.get("type") != "access":
            raise InvalidToken
        try:
            return UUID(payload["sub"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidToken from exc
