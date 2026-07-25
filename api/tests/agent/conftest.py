from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import pytest

from app.config import settings
from app.models import (
    LatLng,
    PendingAction,
    Place,
    ProviderTripState,
    Quote,
    Session,
    Trip,
    TripStatus,
)
from app.providers.uber import ProviderError
from app.storage import ActionLogRepo, PendingActionRepo, SessionRepo, TripRepo


def now() -> datetime:
    return datetime.now(timezone.utc)


def make_quote(*, fare_id: str = "fare-1", expired: bool = False) -> Quote:
    return Quote(
        fare_id=fare_id,
        product_id="uberx-sg",
        product_name="UberX",
        capacity=4,
        price_value=15.5,
        price_display="SGD 15.50",
        currency="SGD",
        pickup_eta_minutes=4,
        duration_minutes=20,
        distance_km=8.2,
        surge_multiplier=1,
        expires_at=now() + timedelta(minutes=-1 if expired else 5),
        pickup=LatLng(lat=1.28, lng=103.86),
        dropoff=LatLng(lat=1.35, lng=103.98),
        pickup_label="Marina Bay Sands",
        dropoff_label="Changi Airport",
    )


def make_session(session_id: str | None = None) -> Session:
    created = now()
    return Session(
        session_id=session_id or str(uuid4()),
        created_at=created,
        updated_at=created,
        expires_at=int(created.timestamp()) + 86400,
    )


def make_trip(
    session_id: str,
    *,
    status: TripStatus = TripStatus.processing,
    request_id: str = "req-1",
) -> Trip:
    created = now()
    return Trip(
        trip_id=f"uber:{request_id}",
        provider="uber",
        provider_request_id=request_id,
        session_id=session_id,
        status=status,
        quote=make_quote(),
        created_at=created,
        updated_at=created,
    )


def make_pending(
    session_id: str,
    *,
    token: str | None = None,
    action_type: str = "book",
    payload: dict | None = None,
    expired: bool = False,
) -> PendingAction:
    created = now()
    return PendingAction(
        token=token or f"token-{uuid4().hex}",
        session_id=session_id,
        action_type=action_type,
        payload=payload or {"quote": make_quote().model_dump(mode="json")},
        correlation_id=f"act_{uuid4().hex[:12]}",
        created_at=created,
        expires_at=int(created.timestamp()) + (-1 if expired else 120),
    )


class CapturePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def publish(self, session_id: str, message: dict) -> None:
        self.messages.append((session_id, message))


class RaisingPublisher:
    async def publish(self, session_id: str, message: dict) -> None:
        raise RuntimeError("publisher down")


class SpyProvider:
    def __init__(self) -> None:
        self.quote_calls = 0
        self.book_calls = []
        self.cancel_calls = []
        self.get_trip_calls = []
        self.failure: ProviderError | None = None
        self.quote_failure: ProviderError | None = None
        self.cancel_status = TripStatus.rider_canceled
        self.get_trip_failure: ProviderError | None = None

    async def get_quotes(self, pickup, dropoff, pickup_label, dropoff_label):
        self.quote_calls += 1
        if self.quote_failure:
            raise self.quote_failure
        return [make_quote()]

    async def book(self, quote, guest):
        self.book_calls.append((quote, guest))
        if self.failure:
            raise self.failure
        return ProviderTripState(provider_request_id="req-booked", status=TripStatus.processing)

    async def get_trip(self, provider_request_id):
        self.get_trip_calls.append(provider_request_id)
        if self.get_trip_failure:
            raise self.get_trip_failure
        return ProviderTripState(provider_request_id=provider_request_id, status=TripStatus.accepted)

    async def cancel(self, provider_request_id):
        self.cancel_calls.append(provider_request_id)
        if self.failure:
            raise self.failure
        return ProviderTripState(
            provider_request_id=provider_request_id,
            status=self.cancel_status,
        )


class StubGeocoder:
    async def search(self, query: str):
        return [
            Place(
                place_id="",
                name=query.upper(),
                address=f"1 {query.upper()} ROAD",
                postal="123456",
                location=LatLng(lat=1.3, lng=103.8),
            )
        ]


@pytest.fixture(autouse=True)
def clean_tables():
    resource = boto3.resource("dynamodb")
    for name in ("sessions", "trips", "action_log", "pending_actions"):
        table = resource.Table(name)
        items = table.scan().get("Items", [])
        with table.batch_writer() as batch:
            for item in items:
                key = {"session_id": item["session_id"]}
                if name == "trips":
                    key = {"trip_id": item["trip_id"]}
                elif name == "action_log":
                    key["entry_key"] = item["entry_key"]
                elif name == "pending_actions":
                    key = {"token": item["token"]}
                batch.delete_item(Key=key)
    yield


@pytest.fixture
def repos():
    return SessionRepo(), TripRepo(), ActionLogRepo(), PendingActionRepo()


@pytest.fixture
def publisher():
    return CapturePublisher()


@pytest.fixture
def provider():
    return SpyProvider()


@pytest.fixture
def config():
    return replace(
        settings,
        openrouter_api_key="test-openrouter-key",
        rider_first_name="Test",
        rider_last_name="Rider",
        rider_phone="+6590000000",
        webhook_shared_secret="webhook-secret",
    )
