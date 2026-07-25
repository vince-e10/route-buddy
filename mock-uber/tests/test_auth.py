def test_v1_routes_require_bearer_and_organization_uuid(client, auth_headers):
    payload = {
        "pickup": {"latitude": 1.30, "longitude": 103.80},
        "dropoff": {"latitude": 1.31, "longitude": 103.81},
    }
    assert client.post("/v1/guests/trips/estimates", json=payload).json() == {
        "code": "unauthorized"
    }
    assert client.post(
        "/v1/guests/trips/estimates", json=payload, headers={"authorization": "Bearer x"}
    ).json() == {"code": "unauthorized"}
    assert client.post("/v1/guests/trips/estimates", json=payload, headers=auth_headers).status_code == 200
