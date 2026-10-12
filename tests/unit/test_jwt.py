from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.domain.errors import InvalidToken
from app.infrastructure.security import JwtTokenService


def test_roundtrip() -> None:
    service = JwtTokenService(secret="s", algorithm="HS256", ttl_minutes=60)
    agent_id = uuid4()

    token = service.create_access_token(agent_id)

    assert service.decode_access_token(token) == agent_id


def test_expired_token_rejected() -> None:
    service = JwtTokenService(secret="s", algorithm="HS256", ttl_minutes=60)
    now = datetime.now(UTC) - timedelta(minutes=120)
    payload = {
        "sub": str(uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=1),
    }
    token = jwt.encode(payload, "s", algorithm="HS256")

    with pytest.raises(InvalidToken):
        service.decode_access_token(token)


def test_malformed_token_rejected() -> None:
    service = JwtTokenService(secret="s", algorithm="HS256", ttl_minutes=60)

    with pytest.raises(InvalidToken):
        service.decode_access_token("not-a-jwt")


def test_wrong_type_rejected() -> None:
    service = JwtTokenService(secret="s", algorithm="HS256", ttl_minutes=60)
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, "s", algorithm="HS256")

    with pytest.raises(InvalidToken):
        service.decode_access_token(token)


def test_wrong_secret_rejected() -> None:
    service = JwtTokenService(secret="s", algorithm="HS256", ttl_minutes=60)
    other = JwtTokenService(secret="other-secret", algorithm="HS256", ttl_minutes=60)
    token = other.create_access_token(uuid4())

    with pytest.raises(InvalidToken):
        service.decode_access_token(token)
