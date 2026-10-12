import dataclasses
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# Ключи, по которым в аудите маскируются персональные данные пассажиров (SPEC §5).
_SENSITIVE_KEYS = {"document_number", "document_expiry"}


def to_jsonable(value: Any) -> Any:
    """Рекурсивно превращает dataclass-ы/Decimal/UUID/datetime в JSON-совместимые типы."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def mask_sensitive(value: Any) -> Any:
    """Маскирует номера/сроки документов пассажиров перед записью в provider_requests."""
    if isinstance(value, dict):
        return {
            key: ("***" if key.lower() in _SENSITIVE_KEYS else mask_sensitive(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def truncate_response(value: Any, max_items: int = 20) -> Any:
    """Усекает длинные списки офферов в аудите, сохраняя общее количество."""
    if isinstance(value, list) and len(value) > max_items:
        return {"items": value[:max_items], "truncated": True, "total": len(value)}
    return value
