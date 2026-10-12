from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PassengerRequest(BaseModel):
    type: str = Field(pattern=r"^(ADT|CHD|INF)$")
    first_name: str
    last_name: str
    birth_date: date
    gender: str = Field(pattern=r"^[MF]$")
    citizenship: str = Field(pattern=r"^[A-Za-z]{2}$")
    document_number: str
    document_expiry: date


class ContactRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(pattern=r"^\+?[0-9]{7,15}$")


class CreateOrderRequest(BaseModel):
    offer_id: UUID
    fare_family: str
    passengers: list[PassengerRequest]
    contact: ContactRequest


class PassengerResponse(BaseModel):
    type: str
    first_name: str
    last_name: str
    birth_date: date
    gender: str
    citizenship: str
    document_number: str
    document_expiry: date


class ContactResponse(BaseModel):
    email: str
    phone: str


class OrderResponse(BaseModel):
    id: UUID
    status: str
    offer_id: UUID
    fare_family: str
    passengers: list[PassengerResponse]
    contact: ContactResponse
    price: Decimal
    currency: str
    expires_at: datetime
    created_at: datetime
    ticket_numbers: list[str]
