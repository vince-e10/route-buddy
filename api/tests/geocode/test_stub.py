import pytest

from app.geocode.base import Geocoder
from app.geocode.stub import DEMO_PLACES, StubGeocoder


@pytest.mark.asyncio
async def test_changi_query_returns_exact_demo_place() -> None:
    places = await StubGeocoder(DEMO_PLACES).search("Take me to changi airport")

    assert places[0].place_id == ""
    assert places[0].name == "CHANGI AIRPORT TERMINAL 3"
    assert places[0].address == "65 AIRPORT BOULEVARD CHANGI AIRPORT TERMINAL 3 SINGAPORE 819663"
    assert places[0].postal == "819663"
    assert places[0].location.lat == 1.35735
    assert places[0].location.lng == 103.98803


@pytest.mark.asyncio
async def test_marina_bay_sands_is_case_insensitive() -> None:
    places = await StubGeocoder(DEMO_PLACES).search("MARINA BAY SANDS")

    assert places[0].name == "MARINA BAY SANDS"
    assert places[0].address == "1 BAYFRONT AVENUE MARINA BAY SANDS SINGAPORE 018971"
    assert places[0].postal == "018971"
    assert places[0].location.lat == 1.28345
    assert places[0].location.lng == 103.86081


@pytest.mark.asyncio
async def test_unknown_query_returns_no_demo_place() -> None:
    assert await StubGeocoder(DEMO_PLACES).search("nowhere") == []


def test_stub_geocoder_satisfies_protocol() -> None:
    geocoder: Geocoder = StubGeocoder(DEMO_PLACES)
    assert geocoder is not None
