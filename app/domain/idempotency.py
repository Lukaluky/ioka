from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class IdempotencyKeyRecord:
    agent_id: UUID
    key: str
    request_hash: str
    order_id: UUID
    created_at: datetime
