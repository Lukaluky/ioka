from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Agent:
    id: UUID
    login: str
    password_hash: str
    name: str
    balance: Decimal
    currency: str
    is_active: bool
    created_at: datetime
