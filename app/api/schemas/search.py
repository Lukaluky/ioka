from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PassengersRequest(BaseModel):
    adults: int = Field(ge=1)
    children: int = Field(ge=0, default=0)
    infants: int = Field(ge=0, default=0)


class SearchRequest(BaseModel):
    origin: str = Field(pattern=r"^[A-Za-z]{3}$")
    destination: str = Field(pattern=r"^[A-Za-z]{3}$")
    departure_date: date
    return_date: date | None = None
    passengers: PassengersRequest
    cabin: str = "economy"


class SearchAcceptedResponse(BaseModel):
    search_id: UUID
    status: str


class SegmentResponse(BaseModel):
    flight_number: str
    airline: str
    origin: str
    destination: str
    departure_utc: datetime
    departure_local: datetime
    arrival_utc: datetime
    arrival_local: datetime
    duration_minutes: int


class OfferResponse(BaseModel):
    offer_id: UUID
    airline: str
    segments: list[SegmentResponse]
    stops: int
    cabin: str
    min_price: Decimal
    currency: str


class SearchStatusResponse(BaseModel):
    search_id: UUID
    status: str
    reason: str | None = None
    offers: list[OfferResponse]


class FareFamilyResponse(BaseModel):
    code: str
    name: str
    price: Decimal
    currency: str
    baggage_kg: int
    carry_on: bool
    refundable: bool
    exchangeable: bool


class OfferDetailResponse(BaseModel):
    offer: OfferResponse
    fare_families: list[FareFamilyResponse]
