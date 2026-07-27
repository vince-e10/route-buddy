import json
import os
import time
import uuid

import boto3
import httpx
import pytest
from boto3.dynamodb.conditions import Key
from websockets.sync.client import connect


API_URL = "http://api:8000"
MOCK_URL = "http://mock-uber:8001"
WAIT_SECONDS = 15


class Chat:
    def __init__(self) -> None:
        self.session_id = str(uuid.uuid4())
        self.messages: list[dict] = []
        self.socket = connect(f"ws://api:8000/ws?session_id={self.session_id}", open_timeout=5)

    def close(self) -> None:
        self.socket.close()

    def send(self, text: str) -> None:
        self.socket.send(json.dumps({"type": "user_msg", "text": text}))

    def select(self, action: str, target_id: str) -> None:
        self.socket.send(
            json.dumps(
                {
                    "type": "action_request",
                    "action": action,
                    "target_id": target_id,
                }
            )
        )

    def next(self, predicate) -> dict:
        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            message = json.loads(self.socket.recv(timeout=remaining))
            self.messages.append(message)
            if predicate(message):
                return message
        raise AssertionError("timed out waiting for WebSocket message")


@pytest.fixture
def chat():
    value = Chat()
    try:
        yield value
    finally:
        value.close()


@pytest.fixture(autouse=True)
def reset_mock_scenario():
    response = httpx.post(f"{MOCK_URL}/_sim/scenario", json={"scenario": "reset"}, timeout=5)
    response.raise_for_status()


def _ddb_table(name: str):
    return boto3.resource("dynamodb", endpoint_url="http://floci:4566").Table(name)


def _wait_for_rows(table, session_id: str, minimum: int = 1) -> list[dict]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        rows = table.query(KeyConditionExpression=Key("session_id").eq(session_id))["Items"]
        if len(rows) >= minimum:
            return rows
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {minimum} {table.table_name} rows")


def _wait_for_trip_count(session_id: str, expected: int) -> list[dict]:
    table = _ddb_table("trips")
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        rows = table.query(
            IndexName="by_session", KeyConditionExpression=Key("session_id").eq(session_id)
        )["Items"]
        if len(rows) == expected:
            return rows
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {expected} trips")


def _assert_trip_count_stays(session_id: str, expected: int) -> None:
    table = _ddb_table("trips")
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        rows = table.query(
            IndexName="by_session", KeyConditionExpression=Key("session_id").eq(session_id)
        )["Items"]
        assert len(rows) == expected
        time.sleep(0.1)


def _trip_item(trip_id: str) -> dict:
    return _ddb_table("trips").get_item(Key={"trip_id": trip_id})["Item"]


def _quote_and_request_book(chat: Chat) -> dict:
    chat.send("Take me from Changi Airport to Marina Bay Sands")
    quotes = chat.next(lambda item: item.get("type") == "quotes")
    assert len(quotes["items"]) == 3
    assert {item["currency"] for item in quotes["items"]} == {"SGD"}
    chat.send("book UberX")
    guidance = chat.next(
        lambda item: item.get("type") == "assistant_msg"
        and "Select" in item.get("text", "")
    )
    assert "exact ride option card" in guidance["text"]
    assert _ddb_table("pending_actions").scan()["Items"] == []
    selected = max(quotes["items"], key=lambda item: item["price_value"])
    assert selected["price_value"] > min(
        item["price_value"] for item in quotes["items"]
    )
    chat.select("book", selected["fare_id"])
    request = chat.next(
        lambda item: item.get("type") == "confirmation_request" and item.get("action") == "book"
    )
    assert request["summary"]["product_name"] == selected["product_name"]
    return request


def _confirm(token: str, decision: str = "confirm") -> dict:
    response = httpx.post(
        f"{API_URL}/confirm", json={"token": token, "decision": decision}, timeout=5
    )
    response.raise_for_status()
    return response.json()


def _book(chat: Chat) -> str:
    request = _quote_and_request_book(chat)
    result = _confirm(request["token"])
    assert result["result"] == "executed"
    assert result["trip_id"]
    chat.next(lambda item: item.get("type") == "confirmation_resolved" and item.get("token") == request["token"])
    return result["trip_id"]


def test_happy_path_streams_driver_lifecycle_in_order(chat):
    trip_id = _book(chat)
    updates = []
    while len(updates) < 5:
        message = chat.next(lambda item: item.get("type") == "trip_update" and item.get("trip_id") == trip_id)
        updates.append(message)
    assert [item["status"] for item in updates] == [
        "processing",
        "accepted",
        "arriving",
        "in_progress",
        "completed",
    ]
    assert all(item["driver"] is None for item in updates[:1])
    assert all(item["driver"] for item in updates[1:])


def test_dismissing_book_request_creates_no_trip(chat):
    request = _quote_and_request_book(chat)
    assert _confirm(request["token"], "dismiss") == {"result": "dismissed", "trip_id": None}
    assert chat.next(
        lambda item: item == {
            "type": "confirmation_resolved",
            "token": request["token"],
            "result": "dismissed",
            "trip_id": None,
        }
    )
    _assert_trip_count_stays(chat.session_id, 0)


def test_cancel_after_accepted_produces_rider_canceled(chat):
    trip_id = _book(chat)
    accepted = chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "accepted"
    )
    assert accepted["driver"]
    chat.select("cancel", trip_id)
    request = chat.next(
        lambda item: item.get("type") == "confirmation_request" and item.get("action") == "cancel"
    )
    assert request["summary"]["trip_id"] == trip_id
    assert _confirm(request["token"])["result"] == "executed"
    canceled = chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "rider_canceled"
    )
    assert canceled["driver"]


def test_two_trip_selection_cancels_only_the_exact_trip(chat):
    first_trip_id = _book(chat)
    second_trip_id = _book(chat)
    assert first_trip_id != second_trip_id

    chat.select("cancel", second_trip_id)
    request = chat.next(
        lambda item: item.get("type") == "confirmation_request"
        and item.get("action") == "cancel"
    )
    assert request["summary"]["trip_id"] == second_trip_id
    result = _confirm(request["token"])
    assert result == {"result": "executed", "trip_id": second_trip_id}
    chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == second_trip_id
        and item.get("status") == "rider_canceled"
    )

    assert _trip_item(second_trip_id)["status"] == "rider_canceled"
    assert _trip_item(first_trip_id)["status"] != "rider_canceled"


def test_dismissing_cancellation_does_not_cancel_the_trip(chat):
    trip_id = _book(chat)
    chat.select("cancel", trip_id)
    request = chat.next(
        lambda item: item.get("type") == "confirmation_request"
        and item.get("action") == "cancel"
    )

    assert _confirm(request["token"], "dismiss") == {
        "result": "dismissed",
        "trip_id": None,
    }
    chat.next(
        lambda item: item.get("type") == "confirmation_resolved"
        and item.get("token") == request["token"]
        and item.get("result") == "dismissed"
    )
    assert _trip_item(trip_id)["status"] != "rider_canceled"

    rows = _wait_for_rows(_ddb_table("action_log"), chat.session_id, minimum=8)
    cancellation = [
        row for row in rows if row.get("tool") in {"cancel_ride", "cancel"}
    ]
    assert not any(row["phase"] == "executed" for row in cancellation)
    assert any(
        row["phase"] == "outcome"
        and row["payload"].get("result") == "aborted_by_user"
        for row in cancellation
    )


def test_no_drivers_scenario_has_no_driver(chat):
    response = httpx.post(
        f"{MOCK_URL}/_sim/scenario", json={"scenario": "no_drivers"}, timeout=5
    )
    response.raise_for_status()
    trip_id = _book(chat)
    update = chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "no_drivers_available"
    )
    assert update["driver"] is None


def test_confirm_token_is_single_use_and_creates_one_trip(chat):
    request = _quote_and_request_book(chat)
    first = _confirm(request["token"])
    second = _confirm(request["token"])
    assert first["result"] == "executed"
    assert second == {"result": "expired", "trip_id": None}
    trips = _wait_for_trip_count(chat.session_id, 1)
    assert len(trips) == 1
    _assert_trip_count_stays(chat.session_id, 1)


def test_action_log_has_search_book_and_applied_webhook_phases(chat):
    trip_id = _book(chat)
    chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "completed"
    )
    rows = _wait_for_rows(_ddb_table("action_log"), chat.session_id, minimum=15)
    rows.sort(key=lambda item: item["entry_key"])
    phases = [(item.get("tool"), item["phase"]) for item in rows]
    expected = [
        ("search_places", "requested"),
        ("search_places", "outcome"),
        ("get_quotes", "requested"),
        ("get_quotes", "outcome"),
        ("book_ride", "requested"),
        ("book_ride", "verified"),
        ("book_ride", "executed"),
        ("book_ride", "outcome"),
    ]
    index = 0
    for phase in phases:
        if phase == expected[index]:
            index += 1
            if index == len(expected):
                break
    assert index == len(expected)
    book_requested = next(
        item
        for item in rows
        if item["tool"] == "book_ride" and item["phase"] == "requested"
    )
    book_rows = [
        item for item in rows if item["correlation_id"] == book_requested["correlation_id"]
    ]
    assert [
        (item["phase"], item["actor"], item["tool"])
        for item in book_rows
    ] == [
        ("requested", "user", "book_ride"),
        ("verified", "system", "book_ride"),
        ("verified", "user", "book"),
        ("executed", "system", "book_ride"),
        ("outcome", "system", "book_ride"),
    ]
    assert set(book_rows[0]["payload"]) == {"fare_id"}
    assert book_rows[1]["payload"] == {"result": "token_created"}
    assert book_rows[2]["payload"] == {"result": "claimed"}
    assert book_rows[3]["payload"]["endpoint"] == "POST /v1/guests/trips"
    assert book_rows[4]["payload"] == {"result": "booked", "trip_id": trip_id}
    webhook_statuses = [
        item["payload"]["status"]
        for item in rows
        if item["actor"] == "webhook" and item["payload"].get("applied") is True
    ]
    assert webhook_statuses == ["accepted", "arriving", "in_progress", "completed"]


def test_stale_quote_and_completed_trip_selections_create_no_pending_action(chat):
    chat.send("Take me from Changi Airport to Marina Bay Sands")
    first = chat.next(lambda item: item.get("type") == "quotes")
    stale_fare = first["items"][0]["fare_id"]
    chat.send("Take me from Changi Airport to Marina Bay Sands")
    chat.next(lambda item: item.get("type") == "quotes")

    chat.select("book", stale_fare)
    assert "latest quote cards" in chat.next(
        lambda item: item.get("type") == "error"
    )["message"]
    assert _ddb_table("pending_actions").scan()["Items"] == []

    trip_id = _book(chat)
    chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "completed"
    )
    chat.select("cancel", trip_id)
    assert "not cancellable" in chat.next(
        lambda item: item.get("type") == "error"
    )["message"]
    assert _ddb_table("pending_actions").scan()["Items"] == []


def test_phone_is_absent_from_session_and_websocket_messages(chat):
    trip_id = _book(chat)
    chat.next(
        lambda item: item.get("type") == "trip_update"
        and item.get("trip_id") == trip_id
        and item.get("status") == "completed"
    )
    phone = os.environ["RIDER_PHONE"]
    session = _ddb_table("sessions").get_item(Key={"session_id": chat.session_id})["Item"]
    assert phone not in json.dumps(session, default=str)
    assert phone not in json.dumps(chat.messages)
