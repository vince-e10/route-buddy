import math
import time


def test_estimates_return_fixed_products_and_contract_fares(client, auth_headers):
    pickup = (1.28345, 103.86081)
    dropoff = (1.35735, 103.98803)
    response = client.post(
        "/v1/guests/trips/estimates",
        headers=auth_headers,
        json={
            "pickup": {"latitude": pickup[0], "longitude": pickup[1]},
            "dropoff": {"latitude": dropoff[0], "longitude": dropoff[1]},
        },
    )
    assert response.status_code == 200
    estimates = response.json()["product_estimates"]
    assert [item["product"]["product_id"] for item in estimates] == [
        "uberx-sg",
        "comfort-sg",
        "uberxl-sg",
    ]
    lat1, lon1, lat2, lon2 = map(math.radians, (*pickup, *dropoff))
    haversine = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    km = 6371.0 * 2 * math.asin(math.sqrt(haversine))
    base_fare = 4.0 + 0.9 * km + 0.15 * (km / 30 * 60)
    assert estimates[0]["estimate_info"]["fare"]["value"] == round(base_fare, 2)
    assert estimates[1]["estimate_info"]["fare"]["value"] == round(base_fare * 1.3, 2)
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
