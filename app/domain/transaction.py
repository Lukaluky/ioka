from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class TransactionKind(StrEnum):
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    TOPUP = "TOPUP"


@dataclass(frozen=True)
class Transaction:
    id: UUID
    agent_id: UUID
    order_id: UUID | None
    kind: TransactionKind
    amount: Decimal
    currency: str
    balance_after: Decimal
    created_at: datetime
