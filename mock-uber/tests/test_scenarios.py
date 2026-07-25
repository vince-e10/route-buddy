from test_trips import estimate, trip_payload


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
        request_id = response.json()["request_id"]
        assert client.get(f"/v1/guests/trips/{request_id}", headers=auth_headers).json()["status"] == expected


def test_scenario_rejects_unknown_name(client):
    assert client.post("/_sim/scenario", json={"scenario": "unknown"}).status_code == 422
