import asyncio
from collections import defaultdict


# ponytail: in-memory locks, single instance; move coordination to DynamoDB if we scale out
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def session_lock(session_id: str) -> asyncio.Lock:
    return _locks[session_id]
