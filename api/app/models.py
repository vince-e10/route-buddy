from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class LatLng(BaseModel):
    lat: float
    lng: float


class Place(BaseModel):
    place_id: str
    name: str
    address: str
    postal: str | None
    location: LatLng


class Quote(BaseModel):
    fare_id: str
    product_id: str
    product_name: str
    capacity: int
    price_value: float
    price_display: str
    currency: str
    pickup_eta_minutes: int
    duration_minutes: int
    distance_km: float
    surge_multiplier: float
    expires_at: datetime
    pickup: LatLng
    dropoff: LatLng
    pickup_label: str
    dropoff_label: str


class GuestProfile(BaseModel):
    first_name: str
    last_name: str
    phone_number: str


class TripStatus(str, Enum):
    processing = "processing"
    no_drivers_available = "no_drivers_available"
    accepted = "accepted"
    arriving = "arriving"
    in_progress = "in_progress"
    completed = "completed"
    driver_canceled = "driver_canceled"
    rider_canceled = "rider_canceled"
    driver_redispatched = "driver_redispatched"


LEGAL_TRANSITIONS: dict[TripStatus, set[TripStatus]] = {
    TripStatus.processing: {TripStatus.accepted, TripStatus.no_drivers_available},
    TripStatus.accepted: {
        TripStatus.arriving,
        TripStatus.driver_canceled,
        TripStatus.rider_canceled,
        TripStatus.driver_redispatched,
    },
    TripStatus.driver_redispatched: {TripStatus.accepted},
    TripStatus.arriving: {
        TripStatus.in_progress,
        TripStatus.driver_canceled,
        TripStatus.rider_canceled,
    },
    TripStatus.in_progress: {TripStatus.completed},
    TripStatus.no_drivers_available: set(),
    TripStatus.completed: set(),
    TripStatus.driver_canceled: set(),
    TripStatus.rider_canceled: set(),
}

CANCELLABLE_STATUSES = {TripStatus.processing, TripStatus.accepted, TripStatus.arriving}


class Driver(BaseModel):
    name: str
    rating: float


class ProviderTripState(BaseModel):
    provider_request_id: str
    status: TripStatus
    driver: Driver | None = None


class Trip(BaseModel):
    trip_id: str
    provider: str
    provider_request_id: str
    session_id: str
    status: TripStatus
    quote: Quote
    driver: Driver | None = None
    last_event_id: str | None = None
    created_at: datetime
    updated_at: datetime


class PendingAction(BaseModel):
    token: str
    session_id: str
    action_type: Literal["book", "cancel"]
    payload: dict
    correlation_id: str
    created_at: datetime
    expires_at: int


class ActionLogEntry(BaseModel):
    session_id: str
    entry_key: str
    correlation_id: str
    phase: Literal["requested", "verified", "executed", "outcome"]
    actor: Literal["llm", "user", "webhook", "system"]
    tool: str | None = None
    payload: dict
    ts: datetime


class Session(BaseModel):
    session_id: str
    messages: list[dict] = []
    places: dict[str, Place] = {}
    quotes: dict[str, Quote] = {}
    created_at: datetime
    updated_at: datetime
    expires_at: int
