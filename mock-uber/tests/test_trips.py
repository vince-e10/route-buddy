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
