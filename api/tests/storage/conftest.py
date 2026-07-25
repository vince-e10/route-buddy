from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import pytest

from app.models import (
    ActionLogEntry,
    Driver,
    LatLng,
    PendingAction,
    Place,
    Quote,
    Session,
    Trip,
    TripStatus,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def quote() -> Quote:
    return Quote(
        fare_id=f"fare-{uuid4().hex}",
        product_id="uberx-sg",
        product_name="UberX",
        capacity=4,
        price_value=15.5,
        price_display="SGD 15.50",
        currency="SGD",
        pickup_eta_minutes=4,
        duration_minutes=20,
        distance_km=8.2,
        surge_multiplier=1.0,
        expires_at=now() + timedelta(minutes=5),
        pickup=LatLng(lat=1.283, lng=103.86),
        dropoff=LatLng(lat=1.35, lng=103.98),
        pickup_label="Marina Bay Sands",
        dropoff_label="Changi Airport",
    )


def session() -> Session:
    created = now()
    return Session(
        session_id=str(uuid4()),
        messages=[],
        places={},
        quotes={},
        created_at=created,
        updated_at=created,
        expires_at=0,
    )


def place(index: int) -> Place:
    return Place(
        place_id=f"place-{index}",
        name=f"Place {index}",
        address=f"{index} Test Road",
        postal="123456",
        location=LatLng(lat=1.2 + index / 1000, lng=103.8 + index / 1000),
    )


def trip(session_id: str, created_at: datetime | None = None) -> Trip:
    created = created_at or now()
    return Trip(
        trip_id=str(uuid4()),
        provider="uber",
        provider_request_id=f"req-{uuid4().hex}",
        session_id=session_id,
        status=TripStatus.processing,
        quote=quote(),
        created_at=created,
        updated_at=created,
    )


def action_log_entry(session_id: str, entry_key: str = "") -> ActionLogEntry:
    return ActionLogEntry(
        session_id=session_id,
        entry_key=entry_key,
        correlation_id=str(uuid4()),
        phase="requested",
        actor="llm",
        tool="get_quotes",
        payload={"fare": 15.5},
        ts=now(),
    )


def pending_action(expires_at: int | None = None) -> PendingAction:
    return PendingAction(
        token=uuid4().hex,
        session_id=str(uuid4()),
        action_type="book",
        payload={"fare": 15.5, "nested": {"id": "fare-1"}},
        correlation_id=str(uuid4()),
        created_at=now(),
        expires_at=expires_at or int(now().timestamp()) + 120,
    )


@pytest.fixture
def dynamodb():
    return boto3.resource("dynamodb")
