import asyncio

import pytest

from app.storage import PendingActionRepo
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
async def test_second_claim_returns_none() -> None:
    original = pending_action()
    repo = PendingActionRepo()
    await repo.put(original)
    assert await repo.claim(original.token) is not None

    assert await repo.claim(original.token) is None


@pytest.mark.asyncio
async def test_claim_returns_none_when_action_is_absent() -> None:
    assert await PendingActionRepo().claim("missing-token") is None


@pytest.mark.asyncio
async def test_claim_returns_none_when_action_is_expired() -> None:
    original = pending_action(expires_at=1)
    repo = PendingActionRepo()
    await repo.put(original)

    assert await repo.claim(original.token) is None


@pytest.mark.asyncio
async def test_ten_concurrent_claims_have_exactly_one_winner() -> None:
    original = pending_action()
    repo = PendingActionRepo()
    await repo.put(original)

    claims = await asyncio.gather(*(repo.claim(original.token) for _ in range(10)))

    assert sum(claim is not None for claim in claims) == 1
