import pytest

from app.models import LEGAL_TRANSITIONS, TripStatus
from app.store import Store


@pytest.mark.asyncio
async def test_transition_trip_rejects_every_illegal_pair():
    store = Store()
    fare_id, _ = await store.issue_fare("uberx-sg", 4.0, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2}, 1.0)
    trip = await store.create_trip("uberx-sg", fare_id, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2}, {"first_name": "A", "last_name": "B", "phone_number": "+6591234567"}, 1.0)
    for old, legal_next in LEGAL_TRANSITIONS.items():
        trip.status = old
        for new in TripStatus:
            if new not in legal_next:
                with pytest.raises(ValueError):
                    await store.transition_trip(trip.request_id, new)
