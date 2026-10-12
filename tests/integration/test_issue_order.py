import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.application.issue_order import IssueOrder
from app.domain.errors import InsufficientFunds, IssueInProgress, ProviderIssueFailed
from app.domain.money import Money
from app.domain.order import Contact, Order, OrderStatus, Passenger, PassengerType
from app.domain.transaction import TransactionKind
from app.infrastructure.db.models import (
    AgentModel,
    OrderModel,
    OrderPassengerModel,
    OrderStatusHistoryModel,
    TransactionModel,
)
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.unit_of_work import SqlUnitOfWork


class ImmediateIssueProvider:
    def __init__(self, ticket_numbers: list[str] | None = None, fail: bool = False) -> None:
        self._ticket_numbers = ticket_numbers or ["999-0000000001"]
        self._fail = fail

    async def search(self, params):
        raise NotImplementedError

    async def get_offer(self, offer_id):
        raise NotImplementedError

    async def issue(self, order_id, offer_id, fare_family, passengers, contact) -> list[str]:
        if self._fail:
            raise RuntimeError("Имитация падения провайдера")
        return self._ticket_numbers


def _passenger() -> Passenger:
    return Passenger(
        type=PassengerType.ADT,
        first_name="IVAN",
        last_name="IVANOV",
        birth_date=date(1990, 1, 1),
        gender="M",
        citizenship="KZ",
        document_number="N1",
        document_expiry=date(2099, 1, 1),
    )


async def _create_agent(balance: Decimal) -> UUID:
    agent_id = uuid4()
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                login=f"issue-test-{agent_id}",
                password_hash="x",
                name="Issue Test",
                balance=balance,
                currency="USD",
                is_active=True,
            )
        )
        await session.commit()
    return agent_id


async def _create_order(agent_id: UUID, price: Decimal) -> UUID:
    order = Order(
        id=uuid4(),
        agent_id=agent_id,
        offer_id=uuid4(),
        fare_family="STANDARD",
        status=OrderStatus.BOOKED,
        passengers=[_passenger()],
        contact=Contact(email="a@example.com", phone="+77001234567"),
        price=Money(price, "USD"),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_at=datetime.now(UTC),
    )
    session_factory = get_session_factory()
    async with session_factory() as session:
        uow = SqlUnitOfWork(session)
        await uow.orders.add(order)
        await uow.commit()
    return order.id


async def _cleanup(agent_ids: list[UUID], order_ids: list[UUID]) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        for order_id in order_ids:
            await session.execute(
                TransactionModel.__table__.delete().where(TransactionModel.order_id == order_id)
            )
            await session.execute(
                OrderStatusHistoryModel.__table__.delete().where(
                    OrderStatusHistoryModel.order_id == order_id
                )
            )
            await session.execute(
                OrderPassengerModel.__table__.delete().where(
                    OrderPassengerModel.order_id == order_id
                )
            )
            await session.execute(OrderModel.__table__.delete().where(OrderModel.id == order_id))
        for agent_id in agent_ids:
            await session.execute(AgentModel.__table__.delete().where(AgentModel.id == agent_id))
        await session.commit()


async def _get_agent_balance(agent_id: UUID) -> Decimal:
    session_factory = get_session_factory()
    async with session_factory() as session:
        model = await session.get(AgentModel, agent_id)
        assert model is not None
        return model.balance


async def _get_transactions(order_id: UUID) -> list[TransactionModel]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(TransactionModel).where(TransactionModel.order_id == order_id)
        )
        return list(result.scalars().all())


async def test_concurrent_issue_of_same_order_debits_exactly_once() -> None:
    agent_id = await _create_agent(Decimal("1000"))
    order_id = await _create_order(agent_id, Decimal("100"))
    session_factory = get_session_factory()
    provider = ImmediateIssueProvider()

    async def _run():
        async with session_factory() as session:
            uow = SqlUnitOfWork(session)
            use_case = IssueOrder(uow, provider)
            return await use_case.execute(agent_id, order_id)

    results = await asyncio.gather(_run(), _run(), return_exceptions=True)

    try:
        issued = [r for r in results if isinstance(r, Order)]
        conflicts = [r for r in results if isinstance(r, IssueInProgress)]
        assert len(issued) == 1
        assert len(conflicts) == 1
        assert issued[0].status == OrderStatus.ISSUED

        transactions = await _get_transactions(order_id)
        debits = [t for t in transactions if t.kind == TransactionKind.DEBIT.value]
        assert len(debits) == 1

        balance = await _get_agent_balance(agent_id)
        assert balance == Decimal("900")
    finally:
        await _cleanup([agent_id], [order_id])


async def test_concurrent_issue_two_orders_shared_balance_one_wins() -> None:
    agent_id = await _create_agent(Decimal("100"))
    order_id_a = await _create_order(agent_id, Decimal("100"))
    order_id_b = await _create_order(agent_id, Decimal("100"))
    session_factory = get_session_factory()
    provider = ImmediateIssueProvider()

    async def _run(order_id: UUID):
        async with session_factory() as session:
            uow = SqlUnitOfWork(session)
            use_case = IssueOrder(uow, provider)
            return await use_case.execute(agent_id, order_id)

    results = await asyncio.gather(_run(order_id_a), _run(order_id_b), return_exceptions=True)

    try:
        issued = [r for r in results if isinstance(r, Order)]
        rejected = [r for r in results if isinstance(r, InsufficientFunds)]
        assert len(issued) == 1
        assert len(rejected) == 1
        assert issued[0].status == OrderStatus.ISSUED

        balance = await _get_agent_balance(agent_id)
        assert balance == Decimal("0")
        assert balance >= Decimal("0")

        all_transactions = await _get_transactions(order_id_a) + await _get_transactions(order_id_b)
        debits = [t for t in all_transactions if t.kind == TransactionKind.DEBIT.value]
        assert len(debits) == 1
    finally:
        await _cleanup([agent_id], [order_id_a, order_id_b])


async def test_provider_failure_refunds_balance_and_logs_debit_and_refund() -> None:
    agent_id = await _create_agent(Decimal("1000"))
    order_id = await _create_order(agent_id, Decimal("100"))
    session_factory = get_session_factory()
    provider = ImmediateIssueProvider(fail=True)

    try:
        async with session_factory() as session:
            uow = SqlUnitOfWork(session)
            use_case = IssueOrder(uow, provider)
            raised = False
            try:
                await use_case.execute(agent_id, order_id)
            except ProviderIssueFailed:
                raised = True
            assert raised

        async with session_factory() as session:
            model = await session.get(OrderModel, order_id)
            assert model is not None
            assert model.status == OrderStatus.ISSUE_FAILED.value

        balance = await _get_agent_balance(agent_id)
        assert balance == Decimal("1000")

        transactions = await _get_transactions(order_id)
        kinds = sorted(t.kind for t in transactions)
        assert kinds == sorted([TransactionKind.DEBIT.value, TransactionKind.REFUND.value])
    finally:
        await _cleanup([agent_id], [order_id])
