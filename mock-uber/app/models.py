from enum import Enum

from pydantic import BaseModel


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
    TripStatus.accepted: {TripStatus.arriving, TripStatus.driver_canceled, TripStatus.rider_canceled, TripStatus.driver_redispatched},
    TripStatus.driver_redispatched: {TripStatus.accepted},
    TripStatus.arriving: {TripStatus.in_progress, TripStatus.driver_canceled, TripStatus.rider_canceled},
    TripStatus.in_progress: {TripStatus.completed},
    TripStatus.no_drivers_available: set(),
    TripStatus.completed: set(),
    TripStatus.driver_canceled: set(),
    TripStatus.rider_canceled: set(),
}
CANCELLABLE_STATUSES = {TripStatus.processing, TripStatus.accepted, TripStatus.arriving}


class Location(BaseModel):
    latitude: float
    longitude: float


class EstimateRequest(BaseModel):
    pickup: Location
    dropoff: Location


class GuestRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None


class TripCreateRequest(BaseModel):
    guest: GuestRequest | None = None
    product_id: str
    fare_id: str
    pickup: Location
    dropoff: Location


class ScenarioRequest(BaseModel):
    scenario: str
    surge_multiplier: float | None = None
