from typing import Protocol

from app.models import Place


class Geocoder(Protocol):
    async def search(self, query: str) -> list[Place]: ...
