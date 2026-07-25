import pytest

from test_trips import estimate, poll_trip_statuses, trip_payload


def test_scenario_controls_are_unauthenticated_and_reset_only_controls(client, auth_headers):
    assert client.post("/_sim/scenario", json={"scenario": "surge", "surge_multiplier": 2.0}).json() == {
        "applied": "surge"
    }
    zero_distance = {
        "pickup": {"latitude": 1.30, "longitude": 103.80},
        "dropoff": {"latitude": 1.30, "longitude": 103.80},
    }
    surged = client.post("/v1/guests/trips/estimates", headers=auth_headers, json=zero_distance).json()["product_estimates"][0]["estimate_info"]["fare"]["value"]
    assert client.post("/_sim/scenario", json={"scenario": "reset"}).json() == {"applied": "reset"}
    normal = client.post("/v1/guests/trips/estimates", headers=auth_headers, json=zero_distance).json()["product_estimates"][0]["estimate_info"]["fare"]["value"]
    assert (surged, normal) == (8.0, 4.0)


def test_no_drivers_and_driver_cancel_are_consumed_by_next_trip(client, auth_headers):
    for scenario, expected in [("no_drivers", "no_drivers_available"), ("driver_cancel", "driver_canceled")]:
        client.post("/_sim/scenario", json={"scenario": scenario})
        response = client.post("/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers)))
        created = response.json()
        statuses, _ = poll_trip_statuses(client, auth_headers, created["request_id"], created["status"])
        assert statuses[-1] == expected


def test_scenario_rejects_unknown_name(client):
    assert client.post("/_sim/scenario", json={"scenario": "unknown"}).status_code == 422


@pytest.mark.parametrize(
    ("first", "latest", "expected"),
    [
        ("no_drivers", "driver_cancel", "driver_canceled"),
        ("driver_cancel", "no_drivers", "no_drivers_available"),
    ],
)
def test_latest_next_trip_scenario_wins_and_is_consumed_once(client, auth_headers, first, latest, expected):
    client.post("/_sim/scenario", json={"scenario": first})
    client.post("/_sim/scenario", json={"scenario": latest})

    created = client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))
    ).json()
    first_statuses, _ = poll_trip_statuses(client, auth_headers, created["request_id"], created["status"])
    assert first_statuses[-1] == expected

    next_created = client.post(
        "/v1/guests/trips", headers=auth_headers, json=trip_payload(estimate(client, auth_headers))
    ).json()
    next_statuses, _ = poll_trip_statuses(
        client, auth_headers, next_created["request_id"], next_created["status"]
    )
    assert next_statuses[-1] == "completed"
