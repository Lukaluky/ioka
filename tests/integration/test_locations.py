from collections.abc import AsyncIterator

import pytest

from app.infrastructure.db.models import LocationModel
from app.infrastructure.db.repositories import SqlLocationRepository
from app.infrastructure.db.session import get_session_factory

# Нарочно бессмысленные имена/коды, чтобы тест не зависел от реальных данных
# OurAirports, загруженных в ту же базу через app.cli.load_airports.
_ROWS = [
    {
        "iata_code": "QZX",
        "name": "Qzx Exact Match Airport",
        "city": "Qzx City",
        "country_code": "ZZ",
        "type": "large_airport",
    },
    {
        "iata_code": "QZ3",
        "name": "Substring Only Airport",
        "city": "New Qzx Town",
        "country_code": "ZZ",
        "type": "medium_airport",
    },
    {
        "iata_code": "QZ1",
        "name": "Qzxam Prefix Airport",
        "city": "Qzxamville",
        "country_code": "ZZ",
        "type": "medium_airport",
    },
    {
        "iata_code": "QZ2",
        "name": "Other Airport",
        "city": "New Qzxamtown",
        "country_code": "ZZ",
        "type": "medium_airport",
    },
]


@pytest.fixture
async def seeded_locations() -> AsyncIterator[None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        for row in _ROWS:
            await session.merge(LocationModel(**row))
        await session.commit()
    yield
    async with session_factory() as session:
        for row in _ROWS:
            obj = await session.get(LocationModel, row["iata_code"])
            if obj is not None:
                await session.delete(obj)
        await session.commit()


async def test_exact_code_match_ranks_first(seeded_locations: None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        results = await SqlLocationRepository(session).search("qzx", limit=50)

    codes = [loc.iata_code for loc in results]
    assert codes[0] == "QZX"
    assert "QZ3" in codes
    assert codes.index("QZX") < codes.index("QZ3")


async def test_prefix_match_ranks_before_substring_only(seeded_locations: None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        results = await SqlLocationRepository(session).search("qzxam", limit=50)

    codes = [loc.iata_code for loc in results]
    assert codes.index("QZ1") < codes.index("QZ2")


async def test_case_insensitive(seeded_locations: None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        results = await SqlLocationRepository(session).search("QZX", limit=50)

    assert results[0].iata_code == "QZX"
