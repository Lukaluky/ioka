from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response, status

from app.api.deps import AirProviderDep, CurrentAgent, OfferLookupDep, UnitOfWorkDep
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.orders import (
    ContactResponse,
    CreateOrderRequest,
    OrderResponse,
    PassengerResponse,
)
from app.application.issue_order import IssueOrder
from app.application.orders import CreateOrder, CreateOrderInput, GetOrder, compute_request_hash
from app.application.tickets import GetTicket
from app.config import get_settings
from app.domain.order import Contact, Order, Passenger, PassengerType

router = APIRouter(prefix="/travel/avia/orders", tags=["orders"])


def _order_to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        status=order.status.value,
        offer_id=order.offer_id,
        fare_family=order.fare_family,
        passengers=[
            PassengerResponse(
                type=p.type.value,
                first_name=p.first_name,
                last_name=p.last_name,
                birth_date=p.birth_date,
                gender=p.gender,
                citizenship=p.citizenship,
                document_number=p.document_number,
                document_expiry=p.document_expiry,
            )
            for p in order.passengers
        ],
        contact=ContactResponse(email=order.contact.email, phone=order.contact.phone),
        price=order.price.amount,
        currency=order.price.currency,
        expires_at=order.expires_at,
        created_at=order.created_at,
        ticket_numbers=order.ticket_numbers,
    )


@router.post(
    "",
    response_model=OrderResponse,
    summary="Создать заказ (бронь)",
    description="Заголовок Idempotency-Key обязателен. Тот же ключ и то же тело возвращают "
    "существующий заказ (200); тот же ключ с другим телом — 409. Цена фиксируется снимком "
    "с офферa на момент брони, валюта заказа должна совпадать с валютой агента.",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "offer_not_found"},
        409: {"model": ErrorResponse, "description": "idempotency_key_reused"},
        422: {"model": ErrorResponse, "description": "validation_error"},
    },
)
async def create_order(
    payload: CreateOrderRequest,
    agent: CurrentAgent,
    uow: UnitOfWorkDep,
    offer_lookup: OfferLookupDep,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> OrderResponse:
    order_input = CreateOrderInput(
        offer_id=payload.offer_id,
        fare_family=payload.fare_family,
        passengers=[
            Passenger(
                type=PassengerType(p.type),
                first_name=p.first_name,
                last_name=p.last_name,
                birth_date=p.birth_date,
                gender=p.gender,
                citizenship=p.citizenship,
                document_number=p.document_number,
                document_expiry=p.document_expiry,
            )
            for p in payload.passengers
        ],
        contact=Contact(email=payload.contact.email, phone=payload.contact.phone),
    )
    request_hash = compute_request_hash(payload.model_dump(mode="json"))

    use_case = CreateOrder(uow, offer_lookup, order_ttl_minutes=get_settings().order_ttl_minutes)
    order, created = await use_case.execute(agent, idempotency_key, order_input, request_hash)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _order_to_response(order)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Статус и детали заказа",
    description="Только свои заказы. Истёкший BOOKED лениво переводится в EXPIRED при обращении.",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "order_not_found"},
    },
)
async def get_order(order_id: UUID, agent: CurrentAgent, uow: UnitOfWorkDep) -> OrderResponse:
    use_case = GetOrder(uow)
    order = await use_case.execute(agent.id, order_id)
    return _order_to_response(order)


@router.post(
    "/{order_id}/issue",
    response_model=OrderResponse,
    summary="Выписка: списание баланса и выдача билета",
    description="Идемпотентен для уже ISSUED (200 без повторного списания). Списание и выписка "
    "атомарны (SPEC §10): при ошибке/таймауте провайдера деньги возвращаются (REFUND), заказ "
    "переходит в ISSUE_FAILED.",
    responses={
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        402: {"model": ErrorResponse, "description": "insufficient_funds"},
        404: {"model": ErrorResponse, "description": "order_not_found"},
        409: {
            "model": ErrorResponse,
            "description": "invalid_order_status | order_expired | issue_in_progress",
        },
        502: {"model": ErrorResponse, "description": "provider_issue_failed"},
    },
)
async def issue_order(
    order_id: UUID,
    agent: CurrentAgent,
    uow: UnitOfWorkDep,
    provider: AirProviderDep,
) -> OrderResponse:
    use_case = IssueOrder(uow, provider)
    order = await use_case.execute(agent.id, order_id)
    return _order_to_response(order)


@router.get(
    "/{order_id}/ticket",
    summary="Скачать PDF билета",
    description="Доступен только для заказов в статусе ISSUED, после того как воркер "
    "сгенерирует PDF (обычно в течение пары секунд после issue).",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF билета"},
        401: {"model": ErrorResponse, "description": "not_authenticated"},
        404: {"model": ErrorResponse, "description": "order_not_found"},
        409: {"model": ErrorResponse, "description": "ticket_not_ready | invalid_order_status"},
    },
)
async def get_ticket(order_id: UUID, agent: CurrentAgent, uow: UnitOfWorkDep) -> Response:
    use_case = GetTicket(uow)
    pdf = await use_case.execute(agent.id, order_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=ticket-{order_id}.pdf"},
    )
