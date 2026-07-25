def test_v1_routes_require_bearer_and_organization_uuid(client, auth_headers):
    payload = {
        "pickup": {"latitude": 1.30, "longitude": 103.80},
        "dropoff": {"latitude": 1.31, "longitude": 103.81},
    }
    missing_both = client.post("/v1/guests/trips/estimates", json=payload)
    assert missing_both.status_code == 401
    assert missing_both.json() == {
        "code": "unauthorized"
    }
    missing_organization = client.post(
        "/v1/guests/trips/estimates", json=payload, headers={"authorization": "Bearer x"}
    )
    assert missing_organization.status_code == 401
    assert missing_organization.json() == {"code": "unauthorized"}
    assert client.post("/v1/guests/trips/estimates", json=payload, headers=auth_headers).status_code == 200
