import asyncio

import pytest

from app.main import app
from app.models import TripStatus
from app.sim import Simulator
from app.store import Store


def estimate(client, headers):
    return client.post(
        "/v1/guests/trips/estimates",
        headers=headers,
        json={
            "pickup": {"latitude": 1.30, "longitude": 103.80},
            "dropoff": {"latitude": 1.31, "longitude": 103.81},
        },
    ).json()["product_estimates"][0]


def trip_payload(estimate, **changes):
    payload = {
        "guest": {"first_name": "Ada", "last_name": "Lovelace", "phone_number": "+6591234567"},
        "product_id": estimate["product"]["product_id"],
        "fare_id": estimate["estimate_info"]["fare_id"],
        "pickup": {"latitude": 1.30, "longitude": 103.80},
        "dropoff": {"latitude": 1.31, "longitude": 103.81},
    }
    payload.update(changes)
    return payload


def poll_trip_statuses(client, headers, request_id, initial_status):
    statuses = [initial_status]
    drivers = {}
    for _ in range(10):
        trip = client.get(f"/v1/guests/trips/{request_id}", headers=headers).json()
        if trip["status"] != statuses[-1]:
            statuses.append(trip["status"])
            drivers[trip["status"]] = trip["driver"]
        if trip["status"] == "completed" or trip["status"].endswith("canceled") or trip["status"] == "no_drivers_available":
            break
    return statuses, drivers


def test_trip_creation_validates_product_fare_and_guest(client, auth_headers):
    quote = estimate(client, auth_headers)
    assert client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(quote, product_id="nope")
    ).json() == {"code": "invalid_product"}
    assert client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(quote, fare_id="fare_missing")
    ).json() == {"code": "fare_expired"}
    assert client.post(
        "/v1/guests/trips",
        headers=auth_headers,
        json=trip_payload(quote, pickup={"latitude": 1.31, "longitude": 103.80}),
    ).json() == {"code": "fare_expired"}
    assert client.post(
        "/v1/guests/trips",
        headers=auth_headers,
        json=trip_payload(quote, guest={"first_name": "Ada", "last_name": "Lovelace", "phone_number": "bad"}),
    ).json() == {"code": "invalid_guest"}
    missing_guest = trip_payload(quote)
    del missing_guest["guest"]
    response = client.post("/v1/guests/trips", headers=auth_headers, json=missing_guest)
    assert response.status_code == 400
    assert response.json() == {"code": "invalid_guest"}


@pytest.mark.parametrize("field", ["first_name", "last_name", "phone_number"])
def test_trip_creation_rejects_each_missing_guest_field(client, auth_headers, field):
    quote = estimate(client, auth_headers)
    payload = trip_payload(quote)
    del payload["guest"][field]
    response = client.post("/v1/guests/trips", headers=auth_headers, json=payload)
    assert response.status_code == 400
    assert response.json() == {"code": "invalid_guest"}


def test_trip_get_and_delete_use_contract_shapes(client, auth_headers, monkeypatch):
    monkeypatch.setenv("MOCK_DETERMINISTIC", "0")
    response = client.post("/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers)))
    created = response.json()
    assert response.status_code == 200
    assert created["request_id"].startswith("req_")
    assert created["status"] == "processing"
    request_id = created["request_id"]
    assert client.get(f"/v1/guests/trips/{request_id}", headers=auth_headers).json()["request_id"] == request_id
    assert client.delete(f"/v1/guests/trips/{request_id}", headers=auth_headers).json()["status"] == "rider_canceled"
    assert client.get("/v1/guests/trips/req_missing", headers=auth_headers).json() == {"code": "not_found"}


def test_deterministic_trip_exposes_every_status_through_public_routes(client, auth_headers):
    created = client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))
    ).json()
    statuses, drivers = poll_trip_statuses(client, auth_headers, created["request_id"], created["status"])

    assert statuses == ["processing", "accepted", "arriving", "in_progress", "completed"]
    assert all(drivers[status] is not None for status in statuses[1:])


def test_deterministic_trip_completes_without_get_observations(client, auth_headers):
    created = client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))
    ).json()

    client.portal.call(asyncio.sleep, 0.3)

    trip = client.get(f"/v1/guests/trips/{created['request_id']}", headers=auth_headers).json()
    assert trip["status"] == "completed"


@pytest.mark.asyncio
async def test_no_drivers_has_no_driver_and_driver_cancel_follows_acceptance(monkeypatch):
    monkeypatch.setenv("MOCK_DETERMINISTIC", "1")
    for scenario, expected in (("no_drivers", TripStatus.no_drivers_available), ("driver_cancel", TripStatus.driver_canceled)):
        store = Store()
        simulator = Simulator(store)
        statuses = []

        async def capture(payload):
            statuses.append(payload["meta"]["status"])

        monkeypatch.setattr(simulator, "deliver_webhook", capture)
        fare_id, fare = await store.issue_fare(
            "uberx-sg", 4.0, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2}, 1.0
        )
        await store.apply_scenario(scenario)
        trip = await store.create_trip(
            "uberx-sg", fare_id, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2},
            {"first_name": "Ada", "last_name": "Lovelace", "phone_number": "+6591234567"}, fare.surge_multiplier,
        )
        await simulator._run(trip.request_id, trip.scenario)
        current = await store.get_trip(trip.request_id)
        assert current.status == expected
        if scenario == "no_drivers":
            assert current.driver is None
            assert statuses == ["no_drivers_available"]
        else:
            assert current.driver is not None
            assert statuses == ["accepted", "driver_canceled"]


def test_delete_accepts_accepted_trip_and_rejects_completed_trip(client, auth_headers, monkeypatch):
    async def do_not_start(_trip):
        return None

    monkeypatch.setattr(app.state.simulator, "start", do_not_start)
    first = client.post("/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))).json()
    client.portal.call(app.state.store.transition_trip, first["request_id"], TripStatus.accepted, {"name": "Aisha Tan", "rating": 4.6})
    canceled = client.delete(f"/v1/guests/trips/{first['request_id']}", headers=auth_headers)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "rider_canceled"

    second = client.post("/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))).json()
    client.portal.call(app.state.store.transition_trip, second["request_id"], TripStatus.accepted, {"name": "Aisha Tan", "rating": 4.6})
    client.portal.call(app.state.store.transition_trip, second["request_id"], TripStatus.arriving)
    client.portal.call(app.state.store.transition_trip, second["request_id"], TripStatus.in_progress)
    client.portal.call(app.state.store.transition_trip, second["request_id"], TripStatus.completed)
    rejected = client.delete(f"/v1/guests/trips/{second['request_id']}", headers=auth_headers)
    assert rejected.status_code == 409
    assert rejected.json() == {"code": "not_cancellable", "status": "completed"}
