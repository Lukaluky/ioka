from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.infrastructure.json_utils import mask_sensitive, to_jsonable, truncate_response


@dataclass(frozen=True)
class _Sample:
    amount: Decimal
    at: datetime


def test_to_jsonable_converts_dataclass_and_scalars() -> None:
    sample = _Sample(amount=Decimal("12.50"), at=datetime(2026, 1, 1, tzinfo=UTC))

    assert to_jsonable(sample) == {"amount": "12.50", "at": "2026-01-01T00:00:00+00:00"}


def test_to_jsonable_converts_uuid_in_dict() -> None:
    value = uuid4()

    assert to_jsonable({"offer_id": value}) == {"offer_id": str(value)}


def test_mask_sensitive_hides_document_fields() -> None:
    payload = {"passengers": [{"document_number": "N123", "first_name": "IVAN"}]}

    masked = mask_sensitive(payload)

    assert masked["passengers"][0]["document_number"] == "***"
    assert masked["passengers"][0]["first_name"] == "IVAN"


def test_truncate_response_marks_long_lists() -> None:
    items = list(range(25))

    result = truncate_response(items, max_items=20)

    assert result == {"items": items[:20], "truncated": True, "total": 25}


def test_truncate_response_keeps_short_lists() -> None:
    items = [1, 2, 3]

    assert truncate_response(items) == items
