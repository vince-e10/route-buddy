from enum import Enum
from typing import Literal

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
    scenario: Literal["no_drivers", "driver_cancel", "surge", "reset"]
    surge_multiplier: float | None = None


class Cancellation(BaseModel):
    min_cancellation_fee: float
    cancellation_grace_period_threshold_sec: int


class Product(BaseModel):
    product_id: str
    display_name: str
    capacity: int
    product_group: Literal["ridesharing"]
    cancellation: Cancellation


class Estimate(BaseModel):
    low_estimate: int
    high_estimate: int
    display: str
    currency_code: Literal["SGD"]


class FareBreakdown(BaseModel):
    type: str
    value: float
    name: str


class FareResponse(BaseModel):
    value: float
    currency_code: Literal["SGD"]
    display: str
    expires_at: int
    fare_breakdown: list[FareBreakdown]


class TripEstimate(BaseModel):
    distance_estimate: float
    distance_unit: Literal["km"]
    duration_estimate: int


class EstimateInfo(BaseModel):
    fare_id: str
    pickup_estimate: int
    estimate: Estimate
    fare: FareResponse
    trip: TripEstimate


class ProductEstimate(BaseModel):
    product: Product
    estimate_info: EstimateInfo
    fulfillment_indicator: Literal["GREEN"]


class EstimatesResponse(BaseModel):
    product_estimates: list[ProductEstimate]


class GuestResponse(BaseModel):
    guest_id: str
    first_name: str
    last_name: str
    phone_number: str


class CreateTripResponse(BaseModel):
    request_id: str
    product_id: str
    status: TripStatus
    surge_multiplier: float
    guest: GuestResponse


class Driver(BaseModel):
    name: str
    rating: float


class TripResponse(BaseModel):
    request_id: str
    status: TripStatus
    driver: Driver | None
    pickup: Location
    destination: Location
    client_fare: str


class ScenarioResponse(BaseModel):
    applied: Literal["no_drivers", "driver_cancel", "surge", "reset"]


class WebhookMeta(BaseModel):
    user_id: Literal["mock-user"]
    org_uuid: str
    resource_id: str
    status: TripStatus


class WebhookEvent(BaseModel):
    event_id: str
    event_time: int
    event_type: Literal["guests.trips.status_changed"]
    resource_href: str
    meta: WebhookMeta
