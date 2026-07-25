import time


def test_estimates_return_fixed_products_and_contract_fares(client, auth_headers):
    response = client.post(
        "/v1/guests/trips/estimates",
        headers=auth_headers,
        json={
            "pickup": {"latitude": 1.30, "longitude": 103.80},
            "dropoff": {"latitude": 1.30, "longitude": 103.80},
        },
    )
    assert response.status_code == 200
    estimates = response.json()["product_estimates"]
    assert [item["product"]["product_id"] for item in estimates] == [
        "uberx-sg",
        "comfort-sg",
        "uberxl-sg",
    ]
    assert [item["estimate_info"]["fare"]["value"] for item in estimates] == [4.0, 5.2, 6.4]
    assert all(item["estimate_info"]["pickup_estimate"] == 4 for item in estimates)
    assert all(299 <= item["estimate_info"]["fare"]["expires_at"] - time.time() <= 301 for item in estimates)


def test_estimates_use_haversine_distance_and_thirty_kmh(client, auth_headers):
    response = client.post(
        "/v1/guests/trips/estimates",
        headers=auth_headers,
        json={
            "pickup": {"latitude": 0, "longitude": 0},
            "dropoff": {"latitude": 0, "longitude": 1},
        },
    )
    trip = response.json()["product_estimates"][0]["estimate_info"]["trip"]
    assert trip["distance_estimate"] == 111.19
    assert trip["duration_estimate"] == 13343
