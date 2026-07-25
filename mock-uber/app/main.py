import math
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.models import EstimateRequest, ScenarioRequest, TripCreateRequest
from app.sim import Simulator
from app.store import Store


app = FastAPI()
app.state.store = Store()
app.state.simulator = Simulator(app.state.store)

PRODUCTS = [
    ("uberx-sg", "UberX", 4, 1.0),
    ("comfort-sg", "Comfort", 4, 1.3),
    ("uberxl-sg", "UberXL", 6, 1.6),
]


@app.middleware("http")
async def require_uber_auth(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        authorization = request.headers.get("authorization", "")
        organization = request.headers.get("x-uber-organizationuuid", "")
        if not authorization.startswith("Bearer ") or not organization:
            return JSONResponse({"code": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def distance_km(pickup, dropoff):
    radius = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (pickup.latitude, pickup.longitude, dropoff.latitude, dropoff.longitude))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(a))


@app.post("/v1/guests/trips/estimates")
async def estimates(body: EstimateRequest):
    store = app.state.store
    km = distance_km(body.pickup, body.dropoff)
    minutes = km / 30 * 60
    surge = await store.current_surge()
    pickup = body.pickup.model_dump()
    dropoff = body.dropoff.model_dump()
    product_estimates = []
    for product_id, display_name, capacity, multiplier in PRODUCTS:
        value = round((4.0 + 0.9 * km + 0.15 * minutes) * multiplier * surge, 2)
        fare_id, fare = await store.issue_fare(product_id, value, pickup, dropoff, surge)
        product_estimates.append({
            "product": {
                "product_id": product_id,
                "display_name": display_name,
                "capacity": capacity,
                "product_group": "ridesharing",
                "cancellation": {"min_cancellation_fee": 6.0, "cancellation_grace_period_threshold_sec": 120},
            },
            "estimate_info": {
                "fare_id": fare_id,
                "pickup_estimate": 4,
                "estimate": {"low_estimate": max(0, math.floor(value - 1)), "high_estimate": math.ceil(value + 2), "display": f"SGD {max(0, math.floor(value - 1))}-{math.ceil(value + 2)}", "currency_code": "SGD"},
                "fare": {"value": value, "currency_code": "SGD", "display": f"SGD {value:.2f}", "expires_at": fare.expires_at, "fare_breakdown": [{"type": "base_fare", "value": value, "name": "Base fare"}]},
                "trip": {"distance_estimate": round(km, 2), "distance_unit": "km", "duration_estimate": round(minutes * 60)},
            },
            "fulfillment_indicator": "GREEN",
        })
    return {"product_estimates": product_estimates}


@app.post("/v1/guests/trips")
async def create_trip(body: TripCreateRequest):
    store = app.state.store
    products = {item[0] for item in PRODUCTS}
    if body.product_id not in products:
        return JSONResponse({"code": "invalid_product"}, status_code=404)
    fare = await store.get_fare(body.fare_id)
    if (
        fare is None
        or fare.product_id != body.product_id
        or fare.pickup != body.pickup.model_dump()
        or fare.dropoff != body.dropoff.model_dump()
        or fare.expires_at <= int(time.time())
    ):
        return JSONResponse({"code": "fare_expired"}, status_code=410)
    guest = body.guest
    if not guest or not guest.first_name or not guest.last_name or not guest.phone_number or not re.fullmatch(r"\+\d{7,15}", guest.phone_number):
        return JSONResponse({"code": "invalid_guest"}, status_code=400)
    trip = await store.create_trip(body.product_id, body.fare_id, body.pickup.model_dump(), body.dropoff.model_dump(), guest.model_dump(), fare.surge_multiplier)
    await app.state.simulator.start(trip)
    return {"request_id": trip.request_id, "product_id": trip.product_id, "status": trip.status.value, "surge_multiplier": trip.surge_multiplier, "guest": {"guest_id": f"guest_{uuid.uuid4().hex}", **trip.guest}}


def trip_response(trip):
    return {"request_id": trip.request_id, "status": trip.status.value, "driver": trip.driver, "pickup": trip.pickup, "destination": trip.dropoff, "client_fare": f"SGD {trip.fare_value:.2f}"}


@app.get("/v1/guests/trips/{request_id}")
async def get_trip(request_id: str):
    trip = await app.state.store.get_trip(request_id)
    if trip is None:
        return JSONResponse({"code": "not_found"}, status_code=404)
    return trip_response(trip)


@app.delete("/v1/guests/trips/{request_id}")
async def delete_trip(request_id: str):
    trip = await app.state.store.cancel_trip(request_id)
    if trip is None:
        current = await app.state.store.get_trip(request_id)
        if current is None:
            return JSONResponse({"code": "not_found"}, status_code=404)
        return JSONResponse({"code": "not_cancellable", "status": current.status.value}, status_code=409)
    await app.state.simulator.cancel(request_id)
    await app.state.simulator.emit(trip)
    return trip_response(trip)


@app.post("/_sim/scenario")
async def scenario(body: ScenarioRequest):
    await app.state.store.apply_scenario(body.scenario, body.surge_multiplier)
    return {"applied": body.scenario}
