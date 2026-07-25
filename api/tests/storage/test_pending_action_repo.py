import asyncio
from threading import Barrier

import pytest

from app.storage import PendingActionRepo
from app.storage._dynamo import _to_ddb
from tests.storage.conftest import pending_action


@pytest.mark.asyncio
async def test_put_claim_roundtrip_preserves_payload() -> None:
    original = pending_action()
    repo = PendingActionRepo()
    await repo.put(original)

    claimed = await repo.claim(original.token)

    assert claimed is not None
    assert claimed.payload == original.payload


@pytest.mark.asyncio
async def test_claim_twice() -> None:
    original = pending_action()
    repo = PendingActionRepo()
    await repo.put(original)
    assert await repo.claim(original.token) is not None

    assert await repo.claim(original.token) is None


@pytest.mark.asyncio
async def test_claim_absent() -> None:
    assert await PendingActionRepo().claim("missing-token") is None


@pytest.mark.asyncio
async def test_claim_expired() -> None:
    original = pending_action(expires_at=1)
    repo = PendingActionRepo()
    await repo.put(original)

    assert await repo.claim(original.token) is None


@pytest.mark.asyncio
async def test_concurrent_claim_single_winner() -> None:
    original = pending_action()
    repo = PendingActionRepo()
    await repo.put(original)

    claims = await asyncio.gather(*(repo.claim(original.token) for _ in range(10)))

    assert sum(claim is not None for claim in claims) == 1


class _OverlappingDeleteTable:
    def __init__(self) -> None:
        self.barrier = Barrier(2)
        self.action = pending_action()

    def delete_item(self, **kwargs):
        self.barrier.wait(timeout=0.1)
        return {"Attributes": _to_ddb(self.action.model_dump(mode="json"))}


@pytest.mark.asyncio
async def test_claim_allows_overlapping_delete_calls() -> None:
    repo = PendingActionRepo.__new__(PendingActionRepo)
    repo._table = _OverlappingDeleteTable()

    claims = await asyncio.gather(repo.claim("first"), repo.claim("second"))

    assert all(claim is not None for claim in claims)
