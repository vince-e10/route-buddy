from typing import Protocol

from app.models import GuestProfile, LatLng, ProviderTripState, Quote


class RideProvider(Protocol):
    async def get_quotes(
        self, pickup: LatLng, dropoff: LatLng, pickup_label: str, dropoff_label: str
    ) -> list[Quote]: ...

    async def book(self, quote: Quote, guest: GuestProfile) -> ProviderTripState: ...

    async def get_trip(self, provider_request_id: str) -> ProviderTripState: ...

    async def cancel(self, provider_request_id: str) -> ProviderTripState: ...
