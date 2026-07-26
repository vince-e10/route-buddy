from datetime import datetime, timedelta, timezone

import boto3
import pytest

from app.geocode.onemap import GeocodeError
from app.agent.tools import (
    ToolContext,
    handle_book_ride,
    handle_cancel_ride,
    handle_get_quotes,
    handle_get_trip_status,
    handle_list_session_trips,
    handle_search_places,
)
from app.agent.tool_contracts import session_tool_schemas
from app.models import Place, TripStatus
from app.providers.uber import ProviderError

from .conftest import StubGeocoder, make_quote, make_session, make_trip


def test_session_tool_schemas_limit_ids_to_current_session_state():
    current = datetime(2026, 7, 26, tzinfo=timezone.utc)
    session = make_session()
    quote = make_quote(fare_id="fare-live").model_copy(
        update={"expires_at": current + timedelta(minutes=1)}
    )
    session.places = {
        "plc-a": Place(
            place_id="plc-a",
            name="A",
            address="A",
            postal=None,
            location=quote.pickup,
        ),
        "plc-b": Place(
            place_id="plc-b",
            name="B",
            address="B",
            postal=None,
            location=quote.dropoff,
        ),
    }
    session.quotes = {
        quote.fare_id: quote,
        "fare-expired": quote.model_copy(update={"expires_at": current}),
    }
    trips = [
        make_trip(session.session_id, status=TripStatus.accepted, request_id="active"),
        make_trip(session.session_id, status=TripStatus.completed, request_id="done"),
    ]

    schemas = {
        schema["function"]["name"]: schema["function"]["parameters"]
        for schema in session_tool_schemas(session, trips, current)
    }

    assert set(schemas) == {
        "search_places",
        "get_quotes",
        "book_ride",
        "get_trip_status",
        "list_session_trips",
        "cancel_ride",
    }
    assert schemas["get_quotes"]["properties"] == {
        "pickup_place_id": {"type": "string", "enum": ["plc-a", "plc-b"]},
        "dropoff_place_id": {"type": "string", "enum": ["plc-a", "plc-b"]},
    }
    assert schemas["book_ride"]["properties"]["fare_id"] == {
        "type": "string",
        "enum": ["fare-live"],
    }
    assert schemas["get_trip_status"]["properties"]["trip_id"] == {
        "type": "string",
        "enum": ["uber:active", "uber:done"],
    }
    assert schemas["cancel_ride"]["properties"]["trip_id"] == {
        "type": "string",
        "enum": ["uber:active"],
    }


def test_session_tool_schemas_omit_tools_without_eligible_values():
    schemas = session_tool_schemas(
        make_session(), [], datetime(2026, 7, 26, tzinfo=timezone.utc)
    )

    assert [schema["function"]["name"] for schema in schemas] == [
        "search_places",
        "list_session_trips",
    ]


def context(repos, provider, publisher, geocoder=None):
    session_repo, trip_repo, action_log_repo, pending_repo = repos
    return ToolContext(
        session_repo=session_repo,
        trip_repo=trip_repo,
        action_log_repo=action_log_repo,
        pending_repo=pending_repo,
        provider=provider,
        geocoder=geocoder or StubGeocoder(),
        publisher=publisher,
        correlation_id="act_test",
    )


@pytest.mark.asyncio
async def test_search_places_assigns_ids_without_coordinates(repos, provider, publisher):
    session = make_session()
    result = await handle_search_places(session, {"query": "changi"}, context(repos, provider, publisher))
    assert result["places"][0]["place_id"].startswith("plc_")
    assert "location" not in result["places"][0]
    assert session.places


@pytest.mark.asyncio
async def test_get_quotes_unknown_place_refused(repos, provider, publisher):
    session = make_session()
    result = await handle_get_quotes(
        session,
        {"pickup_place_id": "missing", "dropoff_place_id": "also-missing"},
        context(repos, provider, publisher),
    )
    assert result == {"error": "unknown place_id missing; call search_places first"}
    assert provider.quote_calls == 0


@pytest.mark.asyncio
async def test_get_quotes_happy_replaces_cache_and_hides_coordinates(repos, provider, publisher):
    session = make_session()
    old = make_quote(fare_id="old")
    session.quotes = {old.fare_id: old}
    session.places = {
        "a": Place(
            place_id="a", name="A", address="A", postal=None, location=old.pickup
        ),
        "b": Place(
            place_id="b", name="B", address="B", postal=None, location=old.dropoff
        ),
    }
    result = await handle_get_quotes(
        session,
        {"pickup_place_id": "a", "dropoff_place_id": "b"},
        context(repos, provider, publisher),
    )
    assert list(session.quotes) == ["fare-1"]
    assert set(result["quotes"][0]) == {
        "fare_id",
        "product_name",
        "price_display",
        "pickup_eta_minutes",
        "duration_minutes",
    }
    assert publisher.messages[0][1]["type"] == "quotes"


@pytest.mark.asyncio
async def test_book_ride_expired_quote_refused(repos, provider, publisher):
    session = make_session()
    quote = make_quote(expired=True)
    session.quotes = {quote.fare_id: quote}
    result = await handle_book_ride(
        session, {"fare_id": quote.fare_id}, context(repos, provider, publisher)
    )
    assert "error" in result
    assert not provider.book_calls


@pytest.mark.asyncio
async def test_book_ride_creates_frozen_pending_action_and_card(repos, provider, publisher):
    session = make_session()
    quote = make_quote()
    session.quotes = {quote.fare_id: quote}
    result = await handle_book_ride(
        session, {"fare_id": quote.fare_id}, context(repos, provider, publisher)
    )
    assert result == {"status": "pending_user_confirmation"}
    action = await repos[3].claim(publisher.messages[0][1]["token"])
    assert action.payload["quote"]["fare_id"] == quote.fare_id
    assert action.correlation_id != "act_test"
    assert publisher.messages[0][1]["type"] == "confirmation_request"
    assert not provider.book_calls


@pytest.mark.asyncio
async def test_cancel_ride_not_cancellable_refused(repos, provider, publisher):
    session = make_session()
    trip = make_trip(session.session_id, status=TripStatus.completed)
    await repos[1].put(trip)
    result = await handle_cancel_ride(
        session, {"trip_id": trip.trip_id}, context(repos, provider, publisher)
    )
    assert "error" in result
    assert not provider.cancel_calls


@pytest.mark.asyncio
async def test_trip_ownership_enforced(repos, provider, publisher):
    session = make_session()
    trip = make_trip("other-session")
    await repos[1].put(trip)
    result = await handle_get_trip_status(
        session, {"trip_id": trip.trip_id}, context(repos, provider, publisher)
    )
    assert "error" in result
    assert not provider.get_trip_calls


@pytest.mark.asyncio
async def test_trip_status_reconciles_authoritative_provider_state(repos, provider, publisher):
    session = make_session()
    trip = make_trip(session.session_id)
    await repos[1].put(trip)
    result = await handle_get_trip_status(
        session, {"trip_id": trip.trip_id}, context(repos, provider, publisher)
    )
    assert result["status"] == "accepted"
    assert (await repos[1].get(trip.trip_id)).status == TripStatus.accepted


@pytest.mark.asyncio
async def test_list_session_trips_and_cancel_card(repos, provider, publisher):
    session = make_session()
    trip = make_trip(session.session_id, status=TripStatus.accepted)
    await repos[1].put(trip)
    listed = await handle_list_session_trips(
        session, {}, context(repos, provider, publisher)
    )
    assert listed["trips"][0]["trip_id"] == trip.trip_id
    result = await handle_cancel_ride(
        session, {"trip_id": trip.trip_id}, context(repos, provider, publisher)
    )
    assert result == {"status": "pending_user_confirmation"}
    assert publisher.messages[-1][1]["action"] == "cancel"
    assert not provider.cancel_calls


@pytest.mark.asyncio
async def test_external_read_failures_return_safe_errors_and_log_outcomes(
    repos, provider, publisher
):
    class FailingGeocoder:
        async def search(self, query):
            raise GeocodeError("safe geocoder failure")

    session = make_session()
    search_result = await handle_search_places(
        session,
        {"query": "x"},
        context(repos, provider, publisher, FailingGeocoder()),
    )
    assert search_result == {"error": "safe geocoder failure"}

    quote = make_quote()
    session.places = {
        "a": Place(place_id="a", name="A", address="A", postal=None, location=quote.pickup),
        "b": Place(place_id="b", name="B", address="B", postal=None, location=quote.dropoff),
    }
    provider.quote_failure = ProviderError("provider_unreachable", 503, "safe provider failure")
    quote_result = await handle_get_quotes(
        session,
        {"pickup_place_id": "a", "dropoff_place_id": "b"},
        context(repos, provider, publisher),
    )
    assert quote_result == {"error": "safe provider failure"}
    rows = boto3.resource("dynamodb").Table("action_log").scan()["Items"]
    assert [row["phase"] for row in rows].count("outcome") == 2
