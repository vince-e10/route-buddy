from datetime import datetime, timezone

import httpx

from app.config import Settings, settings
from app.models import Driver, GuestProfile, LatLng, ProviderTripState, Quote, TripStatus


class ProviderError(Exception):
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


class UberAdapter:
    def __init__(self, config: Settings = settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=config.uber_base_url.rstrip("/"),
            timeout=10.0,
            headers={
                "Authorization": f"Bearer {config.uber_api_token}",
                "X-Uber-OrganizationUUID": config.uber_org_uuid,
                "Content-Type": "application/json",
            },
        )

    async def _request(
        self, method: str, path: str, *, retry_transport: bool = False, **kwargs: object
    ) -> httpx.Response:
        for attempt in range(2 if retry_transport else 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError:
                if retry_transport and attempt == 0:
                    continue
                raise ProviderError(
                    "provider_unreachable", 503, "Ride provider is unavailable."
                ) from None
            if not response.is_success:
                self._raise_response_error(response)
            return response
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_response_error(response: httpx.Response) -> None:
        code = "provider_error"
        detail = "Ride provider request failed."
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            if isinstance(body.get("code"), str):
                code = body["code"]
            if isinstance(body.get("detail"), str):
                detail = body["detail"]
            elif code != "provider_error":
                detail = code
        raise ProviderError(code, response.status_code, detail)

    async def get_quotes(
        self, pickup: LatLng, dropoff: LatLng, pickup_label: str, dropoff_label: str
    ) -> list[Quote]:
        response = await self._request(
            "POST",
            "/v1/guests/trips/estimates",
            retry_transport=True,
            json={
                "pickup": {"latitude": pickup.lat, "longitude": pickup.lng},
                "dropoff": {"latitude": dropoff.lat, "longitude": dropoff.lng},
            },
        )
        return [
            self._quote(item, pickup, dropoff, pickup_label, dropoff_label)
            for item in response.json()["product_estimates"]
        ]

    @staticmethod
    def _quote(
        item: dict,
        pickup: LatLng,
        dropoff: LatLng,
        pickup_label: str,
        dropoff_label: str,
    ) -> Quote:
        product = item["product"]
        info = item["estimate_info"]
        fare = info["fare"]
        trip = info["trip"]
        return Quote(
            fare_id=info["fare_id"],
            product_id=product["product_id"],
            product_name=product["display_name"],
            capacity=product["capacity"],
            price_value=fare["value"],
            price_display=fare["display"],
            currency=fare["currency_code"],
            pickup_eta_minutes=info["pickup_estimate"],
            duration_minutes=trip["duration_estimate"] // 60,
            distance_km=trip["distance_estimate"],
            surge_multiplier=item.get("surge_multiplier", 1.0),
            expires_at=datetime.fromtimestamp(fare["expires_at"], tz=timezone.utc),
            pickup=pickup,
            dropoff=dropoff,
            pickup_label=pickup_label,
            dropoff_label=dropoff_label,
        )

    async def book(self, quote: Quote, guest: GuestProfile) -> ProviderTripState:
        response = await self._request(
            "POST",
            "/v1/guests/trips",
            json={
                "guest": guest.model_dump(),
                "product_id": quote.product_id,
                "fare_id": quote.fare_id,
                "pickup": {"latitude": quote.pickup.lat, "longitude": quote.pickup.lng},
                "dropoff": {"latitude": quote.dropoff.lat, "longitude": quote.dropoff.lng},
            },
        )
        return self._trip_state(response.json())

    async def get_trip(self, provider_request_id: str) -> ProviderTripState:
        response = await self._request(
            "GET", f"/v1/guests/trips/{provider_request_id}", retry_transport=True
        )
        return self._trip_state(response.json())

    async def cancel(self, provider_request_id: str) -> ProviderTripState:
        response = await self._request("DELETE", f"/v1/guests/trips/{provider_request_id}")
        return self._trip_state(response.json())

    @staticmethod
    def _trip_state(body: dict) -> ProviderTripState:
        driver = body.get("driver")
        return ProviderTripState(
            provider_request_id=body["request_id"],
            status=TripStatus(body["status"]),
            driver=Driver(**driver) if driver else None,
        )
