import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.config import Settings
from app.models import GuestProfile, LatLng, Quote, TripStatus
from app.providers.base import RideProvider
from app.providers.uber import ProviderError, UberAdapter


def settings_for_test() -> Settings:
    return Settings(
        openrouter_api_key="",
        openrouter_base_url="https://openrouter.test",
        openrouter_model_primary="model",
        openrouter_model_fallback="fallback",
        llm_mode="fake",
        floci_storage_mode="memory",
        floci_storage_persistent_path="/tmp/floci",
        aws_endpoint_url="http://floci.test",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_default_region="ap-southeast-1",
        uber_base_url="https://uber.test",
        uber_api_token="test-token",
        uber_org_uuid="test-org",
        webhook_shared_secret="",
        onemap_base_url="https://onemap.test",
        onemap_email="",
        onemap_password="",
        rider_first_name="Demo",
        rider_last_name="Rider",
        rider_phone="+6591234567",
        sim_speed=1.0,
        mock_deterministic=True,
        webhook_target_url="http://api.test/webhooks/uber",
    )


ESTIMATES = {
    "product_estimates": [
        {
            "product": {
                "product_id": "uberx-sg",
                "display_name": "UberX",
                "capacity": 4,
                "product_group": "ridesharing",
                "cancellation": {
                    "min_cancellation_fee": 6.0,
                    "cancellation_grace_period_threshold_sec": 120,
                },
            },
            "estimate_info": {
                "fare_id": "fare-test",
                "pickup_estimate": 4,
                "estimate": {
                    "low_estimate": 14,
                    "high_estimate": 18,
                    "display": "SGD 14-18",
                    "currency_code": "SGD",
                },
                "fare": {
                    "value": 15.5,
                    "currency_code": "SGD",
                    "display": "SGD 15.50",
                    "expires_at": 1753430000,
                    "fare_breakdown": [
                        {"type": "base_fare", "value": 15.5, "name": "Base fare"}
                    ],
                },
                "trip": {
                    "distance_estimate": 8.2,
                    "distance_unit": "km",
                    "duration_estimate": 1080,
                },
            },
            "fulfillment_indicator": "GREEN",
        }
    ]
}


def quote() -> Quote:
    return Quote(
        fare_id="fare-test",
        product_id="uberx-sg",
        product_name="UberX",
        capacity=4,
        price_value=15.5,
        price_display="SGD 15.50",
        currency="SGD",
        pickup_eta_minutes=4,
        duration_minutes=18,
        distance_km=8.2,
        surge_multiplier=1.0,
        expires_at=datetime(2025, 7, 25, 7, 53, 20, tzinfo=timezone.utc),
        pickup=LatLng(lat=1.28345, lng=103.86081),
        dropoff=LatLng(lat=1.35735, lng=103.98803),
        pickup_label="Marina Bay Sands",
        dropoff_label="Changi Airport",
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_quotes_maps_contract_and_headers() -> None:
    route = respx.post("https://uber.test/v1/guests/trips/estimates").respond(200, json=ESTIMATES)
    adapter = UberAdapter(settings_for_test())

    quotes = await adapter.get_quotes(
        LatLng(lat=1.28345, lng=103.86081),
        LatLng(lat=1.35735, lng=103.98803),
        "Marina Bay Sands",
        "Changi Airport",
    )

    assert route.called
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-token"
    assert request.headers["x-uber-organizationuuid"] == "test-org"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "pickup": {"latitude": 1.28345, "longitude": 103.86081},
        "dropoff": {"latitude": 1.35735, "longitude": 103.98803},
    }
    assert quotes == [quote()]
    assert quotes[0].expires_at.tzinfo == timezone.utc


@pytest.mark.asyncio
@respx.mock
async def test_book_sends_contract_payload_and_maps_processing() -> None:
    route = respx.post("https://uber.test/v1/guests/trips").respond(
        200,
        json={
            "request_id": "req-test",
            "product_id": "uberx-sg",
            "status": "processing",
            "surge_multiplier": 1.0,
            "guest": {"guest_id": "guest-test"},
        },
    )
    adapter = UberAdapter(settings_for_test())

    trip = await adapter.book(
        quote(), GuestProfile(first_name="Demo", last_name="Rider", phone_number="+6591234567")
    )

    assert json.loads(route.calls[0].request.content) == {
        "guest": {"first_name": "Demo", "last_name": "Rider", "phone_number": "+6591234567"},
        "product_id": "uberx-sg",
        "fare_id": "fare-test",
        "pickup": {"latitude": 1.28345, "longitude": 103.86081},
        "dropoff": {"latitude": 1.35735, "longitude": 103.98803},
    }
    assert trip.provider_request_id == "req-test"
    assert trip.status is TripStatus.processing
    assert trip.driver is None


@pytest.mark.asyncio
@respx.mock
async def test_get_trip_maps_present_driver() -> None:
    respx.get("https://uber.test/v1/guests/trips/req-test").respond(
        200,
        json={
            "request_id": "req-test",
            "status": "accepted",
            "driver": {"name": "Ada", "rating": 4.8},
            "pickup": {},
            "destination": {},
            "client_fare": "SGD 15.50",
        },
    )

    trip = await UberAdapter(settings_for_test()).get_trip("req-test")

    assert trip.provider_request_id == "req-test"
    assert trip.status is TripStatus.accepted
    assert trip.driver is not None
    assert trip.driver.name == "Ada"
    assert trip.driver.rating == 4.8


@pytest.mark.asyncio
@respx.mock
async def test_cancel_maps_rider_canceled() -> None:
    respx.delete("https://uber.test/v1/guests/trips/req-test").respond(
        200, json={"request_id": "req-test", "status": "rider_canceled", "driver": None}
    )

    trip = await UberAdapter(settings_for_test()).cancel("req-test")

    assert trip.provider_request_id == "req-test"
    assert trip.status is TripStatus.rider_canceled


@pytest.mark.asyncio
@respx.mock
async def test_book_raises_safe_provider_error_for_expired_fare() -> None:
    respx.post("https://uber.test/v1/guests/trips").respond(410, json={"code": "fare_expired"})

    with pytest.raises(ProviderError) as raised:
        await UberAdapter(settings_for_test()).book(
            quote(), GuestProfile(first_name="Demo", last_name="Rider", phone_number="+6591234567")
        )

    assert raised.value.code == "fare_expired"
    assert raised.value.status_code == 410
    assert raised.value.detail == "fare_expired"


@pytest.mark.asyncio
@respx.mock
async def test_cancel_raises_provider_error_when_not_cancellable() -> None:
    respx.delete("https://uber.test/v1/guests/trips/req-test").respond(
        409, json={"code": "not_cancellable", "status": "completed"}
    )

    with pytest.raises(ProviderError) as raised:
        await UberAdapter(settings_for_test()).cancel("req-test")

    assert raised.value.code == "not_cancellable"
    assert raised.value.status_code == 409


@pytest.mark.asyncio
@respx.mock
async def test_transport_error_is_safe_provider_error() -> None:
    respx.post("https://uber.test/v1/guests/trips").mock(
        side_effect=httpx.ConnectError("unreachable")
    )

    with pytest.raises(ProviderError) as raised:
        await UberAdapter(settings_for_test()).book(
            quote(), GuestProfile(first_name="Demo", last_name="Rider", phone_number="+6591234567")
        )

    assert raised.value.code == "provider_unreachable"
    assert raised.value.status_code == 503
    assert raised.value.detail == "Ride provider is unavailable."


@pytest.mark.asyncio
@respx.mock
async def test_book_does_not_retry_transport_error() -> None:
    route = respx.post("https://uber.test/v1/guests/trips").mock(
        side_effect=httpx.ConnectError("unreachable")
    )

    with pytest.raises(ProviderError):
        await UberAdapter(settings_for_test()).book(
            quote(), GuestProfile(first_name="Demo", last_name="Rider", phone_number="+6591234567")
        )

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_trip_retries_once_after_transport_error() -> None:
    route = respx.get("https://uber.test/v1/guests/trips/req-test").mock(
        side_effect=[
            httpx.ConnectError("unreachable"),
            httpx.Response(200, json={"request_id": "req-test", "status": "processing"}),
        ]
    )

    trip = await UberAdapter(settings_for_test()).get_trip("req-test")

    assert route.call_count == 2
    assert trip.status is TripStatus.processing


def test_uber_adapter_satisfies_provider_protocol() -> None:
    provider: RideProvider = UberAdapter(settings_for_test())
    assert provider is not None
