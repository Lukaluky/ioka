from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AgentMeResponse(BaseModel):
    id: UUID
    login: str
    name: str
    balance: Decimal
    currency: str
    is_active: bool
