import httpx
import pytest
import respx

import app.geocode.onemap as onemap
from app.config import Settings
from app.geocode.base import Geocoder
from app.geocode.onemap import GeocodeError, OneMapGeocoder


def settings_for_test() -> Settings:
    return Settings(
        openrouter_api_key="",
        openrouter_base_url="https://openrouter.test",
        openrouter_model_primary="model",
        openrouter_model_fallback="fallback",
        llm_mode="fake",
        floci_storage_mode="memory",
        floci_storage_persistent_path="/tmp/floci",
        aws_endpoint_url="http://floci.test",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_default_region="ap-southeast-1",
        uber_base_url="https://uber.test",
        uber_api_token="test-token",
        uber_org_uuid="test-org",
        webhook_shared_secret="",
        onemap_base_url="https://onemap.test",
        onemap_email="user@example.test",
        onemap_password="test-password",
        rider_first_name="Demo",
        rider_last_name="Rider",
        rider_phone="+6591234567",
        sim_speed=1.0,
        mock_deterministic=True,
        webhook_target_url="http://api.test/webhooks/uber",
    )


TOKEN = {"access_token": "test-access-token", "expiry_timestamp": "2000000000"}
RESULT = {
    "SEARCHVAL": "MARINA BAY SANDS",
    "BLK_NO": "1",
    "ROAD_NAME": "BAYFRONT AVENUE",
    "BUILDING": "MARINA BAY SANDS",
    "ADDRESS": "1 BAYFRONT AVENUE MARINA BAY SANDS SINGAPORE 018971",
    "POSTAL": "018971",
    "X": "31059.4625855722",
    "Y": "29543.3804153632",
    "LATITUDE": "1.28345419690844",
    "LONGITUDE": "103.860809048956",
}
SEARCH = {"found": 1, "totalNumPages": 1, "pageNum": 1, "results": [RESULT]}
TOKEN_URL = "https://onemap.test/api/auth/post/getToken"
SEARCH_URL = "https://onemap.test/api/common/elastic/search"


@pytest.mark.asyncio
@respx.mock
async def test_two_searches_share_one_token_and_map_place() -> None:
    token_route = respx.post(TOKEN_URL).respond(200, json=TOKEN)
    search_route = respx.get(SEARCH_URL).respond(200, json=SEARCH)
    adapter = OneMapGeocoder(settings_for_test())

    first = await adapter.search("marina bay sands")
    second = await adapter.search("marina bay sands")

    assert token_route.call_count == 1
    assert search_route.call_count == 2
    assert first == second
    assert first[0].place_id == ""
    assert first[0].name == "MARINA BAY SANDS"
    assert first[0].address == "1 BAYFRONT AVENUE MARINA BAY SANDS SINGAPORE 018971"
    assert first[0].postal == "018971"
    assert first[0].location.lat == 1.28345419690844
    assert first[0].location.lng == 103.860809048956
    request = search_route.calls[0].request
    assert dict(request.url.params) == {
        "searchVal": "marina bay sands",
        "returnGeom": "Y",
        "getAddrDetails": "Y",
        "pageNum": "1",
    }
    assert request.headers["authorization"] == "test-access-token"


@pytest.mark.asyncio
@respx.mock
async def test_token_expiring_within_one_hour_is_refreshed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onemap.time, "time", lambda: 1_000)
    token_route = respx.post(TOKEN_URL).respond(200, json=TOKEN)
    respx.get(SEARCH_URL).respond(200, json=SEARCH)
    adapter = OneMapGeocoder(settings_for_test())
    adapter._token = "old-token"
    adapter._token_expiry = 1_100

    await adapter.search("marina bay sands")

    assert token_route.call_count == 1


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("postal", ["NIL", "", None])
async def test_blank_or_nil_postal_maps_to_none(postal: str | None) -> None:
    result = {**RESULT, "POSTAL": postal}
    respx.post(TOKEN_URL).respond(200, json=TOKEN)
    respx.get(SEARCH_URL).respond(200, json={**SEARCH, "results": [result]})

    places = await OneMapGeocoder(settings_for_test()).search("marina bay sands")

    assert places[0].postal is None


@pytest.mark.asyncio
@respx.mock
async def test_malformed_coordinates_are_skipped_without_secrets_in_warning(caplog: pytest.LogCaptureFixture) -> None:
    bad = {**RESULT, "SEARCHVAL": "BROKEN PLACE", "LATITUDE": "not-a-number"}
    respx.post(TOKEN_URL).respond(200, json=TOKEN)
    respx.get(SEARCH_URL).respond(200, json={**SEARCH, "found": 2, "results": [bad, RESULT]})

    places = await OneMapGeocoder(settings_for_test()).search("marina bay sands")

    assert [place.name for place in places] == ["MARINA BAY SANDS"]
    assert "BROKEN PLACE" in caplog.text
    assert "test-password" not in caplog.text
    assert "test-access-token" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_401_refreshes_once_then_retries_search() -> None:
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json=TOKEN),
            httpx.Response(200, json={"access_token": "refreshed-token", "expiry_timestamp": "2000000000"}),
        ]
    )
    search_route = respx.get(SEARCH_URL).mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=SEARCH)]
    )

    places = await OneMapGeocoder(settings_for_test()).search("marina bay sands")

    assert [place.name for place in places] == ["MARINA BAY SANDS"]
    assert token_route.call_count == 2
    assert search_route.call_count == 2
    assert search_route.calls[1].request.headers["authorization"] == "refreshed-token"


@pytest.mark.asyncio
@respx.mock
async def test_second_401_raises_safe_geocode_error() -> None:
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json=TOKEN),
            httpx.Response(200, json={"access_token": "refreshed-token", "expiry_timestamp": "2000000000"}),
        ]
    )
    respx.get(SEARCH_URL).mock(side_effect=[httpx.Response(401), httpx.Response(401)])

    with pytest.raises(GeocodeError) as raised:
        await OneMapGeocoder(settings_for_test()).search("marina bay sands")

    assert raised.value.detail == "Geocoding service is unavailable."


@pytest.mark.asyncio
@respx.mock
async def test_not_found_returns_empty_list() -> None:
    respx.post(TOKEN_URL).respond(200, json=TOKEN)
    respx.get(SEARCH_URL).respond(200, json={"found": 0, "totalNumPages": 0, "pageNum": 1, "results": []})

    assert await OneMapGeocoder(settings_for_test()).search("unknown") == []


@pytest.mark.asyncio
@respx.mock
async def test_results_are_capped_at_ten() -> None:
    results = [{**RESULT, "SEARCHVAL": f"PLACE {number}"} for number in range(11)]
    respx.post(TOKEN_URL).respond(200, json=TOKEN)
    respx.get(SEARCH_URL).respond(200, json={"found": 11, "totalNumPages": 2, "pageNum": 1, "results": results})

    places = await OneMapGeocoder(settings_for_test()).search("place")

    assert len(places) == 10
    assert places[-1].name == "PLACE 9"


def test_onemap_geocoder_satisfies_protocol() -> None:
    geocoder: Geocoder = OneMapGeocoder(settings_for_test())
    assert geocoder is not None
