from uuid import uuid4

import pytest

from app.application.search import GetSearchResult
from app.domain.errors import SearchNotFound
from app.domain.search import SearchResult, SearchStatus
from tests.unit.test_search import FakeSearchStore


async def test_unknown_search_id_raises_not_found() -> None:
    use_case = GetSearchResult(FakeSearchStore())

    with pytest.raises(SearchNotFound):
        await use_case.execute(uuid4(), uuid4())


async def test_foreign_agent_raises_not_found() -> None:
    store = FakeSearchStore()
    owner_id = uuid4()
    search_id = uuid4()
    store.saved.append(SearchResult(search_id, owner_id, SearchStatus.DONE, offers=[]))
    use_case = GetSearchResult(store)

    with pytest.raises(SearchNotFound):
        await use_case.execute(uuid4(), search_id)


async def test_owner_gets_own_result() -> None:
    store = FakeSearchStore()
    owner_id = uuid4()
    search_id = uuid4()
    store.saved.append(SearchResult(search_id, owner_id, SearchStatus.DONE, offers=[]))
    use_case = GetSearchResult(store)

    result = await use_case.execute(owner_id, search_id)

    assert result.search_id == search_id
