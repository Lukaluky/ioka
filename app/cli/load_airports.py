"""CLI: загрузить аэропорты из справочника OurAirports в таблицу locations (идемпотентно)."""

import asyncio
import csv
import io

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.infrastructure.db.models import LocationModel
from app.infrastructure.db.session import get_session_factory

AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
ALLOWED_TYPES = {"large_airport", "medium_airport"}
CHUNK_SIZE = 500


def _parse_rows(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in reader:
        iata_code = (row.get("iata_code") or "").strip().upper()
        airport_type = (row.get("type") or "").strip()
        if len(iata_code) != 3 or not iata_code.isalpha() or airport_type not in ALLOWED_TYPES:
            continue
        if iata_code in seen:
            continue
        seen.add(iata_code)
        rows.append(
            {
                "iata_code": iata_code,
                "name": (row.get("name") or "").strip(),
                "city": (row.get("municipality") or "").strip(),
                "country_code": (row.get("iso_country") or "").strip(),
                "type": airport_type,
            }
        )
    return rows


async def _upsert(rows: list[dict[str, str]]) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        for start in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[start : start + CHUNK_SIZE]
            stmt = pg_insert(LocationModel).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[LocationModel.iata_code],
                set_={
                    "name": stmt.excluded.name,
                    "city": stmt.excluded.city,
                    "country_code": stmt.excluded.country_code,
                    "type": stmt.excluded.type,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def _main_async() -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(AIRPORTS_CSV_URL)
        response.raise_for_status()
    rows = _parse_rows(response.text)
    await _upsert(rows)
    print(f"Загружено аэропортов: {len(rows)}")


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
