from app.application.ports import LocationRepository
from app.domain.location import Location


class SearchLocations:
    def __init__(self, locations: LocationRepository) -> None:
        self._locations = locations

    async def execute(self, query: str, limit: int) -> list[Location]:
        return await self._locations.search(query.strip(), limit)
