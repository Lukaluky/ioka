from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports import IdempotencyKeyConflict
from app.domain.idempotency import IdempotencyKeyRecord
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from app.infrastructure.db.models import (
    IdempotencyKeyModel,
    OrderModel,
    OrderPassengerModel,
    OrderStatusHistoryModel,
)


class SqlOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        model = OrderModel(
            id=order.id,
            agent_id=order.agent_id,
            offer_id=order.offer_id,
            fare_family=order.fare_family,
            status=order.status.value,
            price_amount=order.price.amount,
            price_currency=order.price.currency,
            contact_email=order.contact.email,
            contact_phone=order.contact.phone,
            expires_at=order.expires_at,
            created_at=order.created_at,
            passengers=[
                OrderPassengerModel(
                    id=uuid4(),
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
        )
        self._session.add(model)
        await self._session.flush()

    async def get(self, order_id: UUID) -> Order | None:
        model = await self._session.get(OrderModel, order_id)
        return _order_to_domain(model) if model is not None else None

    async def get_for_update(self, order_id: UUID) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.id == order_id).with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _order_to_domain(model) if model is not None else None

    async def update_status(self, order: Order) -> None:
        model = await self._session.get(OrderModel, order.id)
        if model is None:
            return
        model.status = order.status.value
        await self._session.flush()

    async def set_ticket_numbers(self, order_id: UUID, ticket_numbers: list[str]) -> None:
        model = await self._session.get(OrderModel, order_id)
        if model is None:
            return
        model.ticket_numbers = ticket_numbers
        await self._session.flush()

    async def add_status_history(
        self,
        order_id: UUID,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        reason: str | None,
    ) -> None:
        self._session.add(
            OrderStatusHistoryModel(
                id=uuid4(),
                order_id=order_id,
                from_status=from_status.value if from_status is not None else None,
                to_status=to_status.value,
                reason=reason,
            )
        )
        await self._session.flush()


class SqlIdempotencyKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, agent_id: UUID, key: str) -> IdempotencyKeyRecord | None:
        model = await self._session.get(IdempotencyKeyModel, (agent_id, key))
        if model is None:
            return None
        return IdempotencyKeyRecord(
            agent_id=model.agent_id,
            key=model.key,
            request_hash=model.request_hash,
            order_id=model.order_id,
            created_at=model.created_at,
        )

    async def add(self, agent_id: UUID, key: str, request_hash: str, order_id: UUID) -> None:
        self._session.add(
            IdempotencyKeyModel(
                agent_id=agent_id, key=key, request_hash=request_hash, order_id=order_id
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise IdempotencyKeyConflict from exc


def _order_to_domain(model: OrderModel) -> Order:
    return Order(
        id=model.id,
        agent_id=model.agent_id,
        offer_id=model.offer_id,
        fare_family=model.fare_family,
        status=OrderStatus(model.status),
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
            for p in model.passengers
        ],
        contact=Contact(email=model.contact_email, phone=model.contact_phone),
        price=Money(model.price_amount, model.price_currency),
        expires_at=model.expires_at,
        created_at=model.created_at,
        ticket_numbers=list(model.ticket_numbers),
    )
