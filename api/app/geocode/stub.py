from app.models import LatLng, Place


DEMO_PLACES = {
    "changi airport": Place(
        place_id="",
        name="CHANGI AIRPORT TERMINAL 3",
        address="65 AIRPORT BOULEVARD CHANGI AIRPORT TERMINAL 3 SINGAPORE 819663",
        postal="819663",
        location=LatLng(lat=1.35735, lng=103.98803),
    ),
    "marina bay sands": Place(
        place_id="",
        name="MARINA BAY SANDS",
        address="1 BAYFRONT AVENUE MARINA BAY SANDS SINGAPORE 018971",
        postal="018971",
        location=LatLng(lat=1.28345, lng=103.86081),
    ),
}


class StubGeocoder:
    def __init__(self, places: dict[str, Place]) -> None:
        self._places = places

    async def search(self, query: str) -> list[Place]:
        lowered = query.lower()
        for key, place in self._places.items():
            if key in lowered:
                return [place]
        return []
