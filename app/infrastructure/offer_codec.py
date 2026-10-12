"""Восстановление доменных объектов Offer/OfferDetail из JSON, полученного из Redis."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.money import Money
from app.domain.offer import FareFamily, Offer, OfferDetail, Segment


def _money_from_dict(data: dict[str, Any]) -> Money:
    return Money(amount=Decimal(data["amount"]), currency=data["currency"])


def _segment_from_dict(data: dict[str, Any]) -> Segment:
    return Segment(
        flight_number=data["flight_number"],
        airline=data["airline"],
        origin=data["origin"],
        destination=data["destination"],
        departure_utc=datetime.fromisoformat(data["departure_utc"]),
        departure_local=datetime.fromisoformat(data["departure_local"]),
        arrival_utc=datetime.fromisoformat(data["arrival_utc"]),
        arrival_local=datetime.fromisoformat(data["arrival_local"]),
        duration_minutes=data["duration_minutes"],
    )


def offer_from_dict(data: dict[str, Any]) -> Offer:
    return Offer(
        offer_id=UUID(data["offer_id"]),
        airline=data["airline"],
        segments=[_segment_from_dict(s) for s in data["segments"]],
        stops=data["stops"],
        cabin=data["cabin"],
        min_price=_money_from_dict(data["min_price"]),
    )


def _fare_family_from_dict(data: dict[str, Any]) -> FareFamily:
    return FareFamily(
        code=data["code"],
        name=data["name"],
        price=_money_from_dict(data["price"]),
        baggage_kg=data["baggage_kg"],
        carry_on=data["carry_on"],
        refundable=data["refundable"],
        exchangeable=data["exchangeable"],
    )


def offer_detail_from_dict(data: dict[str, Any]) -> OfferDetail:
    return OfferDetail(
        offer=offer_from_dict(data["offer"]),
        fare_families=[_fare_family_from_dict(f) for f in data["fare_families"]],
    )
