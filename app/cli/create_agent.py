"""CLI: создать агента. Пароль вводится интерактивно, в аргументах командной строки его нет."""

import argparse
import asyncio
import getpass
import sys
from decimal import Decimal

from app.infrastructure.db.models import AgentModel
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.security import BcryptPasswordHasher


async def _create_agent(
    login: str, name: str, balance: Decimal, currency: str, password: str
) -> None:
    password_hash = await BcryptPasswordHasher().hash(password)
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(
            AgentModel(
                login=login,
                password_hash=password_hash,
                name=name,
                balance=balance,
                currency=currency,
                is_active=True,
            )
        )
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать агента")
    parser.add_argument("--login", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--balance", type=Decimal, default=Decimal("0"))
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args()

    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Повторите пароль: "):
        print("Пароли не совпадают", file=sys.stderr)
        raise SystemExit(1)

    asyncio.run(_create_agent(args.login, args.name, args.balance, args.currency, password))
    print(f"Агент {args.login} создан")


if __name__ == "__main__":
    main()
