import json

import pytest

from app.agent.fake_llm import FakeLLM


async def complete(messages):
    return await FakeLLM().complete(messages, [])


@pytest.mark.asyncio
async def test_search_flow_is_transcript_driven():
    messages = [{"role": "user", "content": "Take me from Changi Airport to Marina Bay Sands"}]
    response = await complete(messages)
    assert json.loads(response.tool_calls[0].arguments) == {"query": "Changi Airport"}
    messages += [
        {"role": "assistant", "tool_calls": [{"id": "search_pickup"}]},
        {
            "role": "tool",
            "tool_call_id": response.tool_calls[0].id,
            "content": '{"places":[{"place_id":"p1"}]}',
        },
    ]
    response = await complete(messages)
    assert json.loads(response.tool_calls[0].arguments) == {"query": "Marina Bay Sands"}
    messages += [
        {"role": "assistant", "tool_calls": [{"id": "search_dropoff"}]},
        {
            "role": "tool",
            "tool_call_id": response.tool_calls[0].id,
            "content": '{"places":[{"place_id":"p2"}]}',
        },
    ]
    response = await complete(messages)
    assert json.loads(response.tool_calls[0].arguments) == {
        "pickup_place_id": "p1",
        "dropoff_place_id": "p2",
    }


@pytest.mark.asyncio
async def test_book_flow_picks_cheapest_quote():
    response = await complete(
        [
            {"role": "user", "content": "book uberx"},
            {
                "role": "tool",
                "tool_call_id": "q",
                "content": '{"quotes":[{"fare_id":"high","price_display":"SGD 20","price_value":20},'
                '{"fare_id":"low","price_display":"SGD 10","price_value":10}]}',
            },
        ]
    )
    assert json.loads(response.tool_calls[0].arguments) == {"fare_id": "low"}


@pytest.mark.asyncio
async def test_cancel_flow_picks_latest_cancellable_trip():
    response = await complete(
        [
            {"role": "user", "content": "cancel that"},
            {
                "role": "tool",
                "tool_call_id": "trips",
                "content": '{"trips":[{"trip_id":"old","status":"completed","created_at":"1"},'
                '{"trip_id":"new","status":"accepted","created_at":"2"}]}',
            },
        ]
    )
    assert response.tool_calls[0].name == "cancel_ride"
    assert json.loads(response.tool_calls[0].arguments) == {"trip_id": "new"}


@pytest.mark.asyncio
async def test_status_and_fallback_text():
    status = await complete(
        [
            {"role": "user", "content": "status please"},
            {
                "role": "tool",
                "tool_call_id": "trips",
                "content": '{"trips":[{"trip_id":"t1","status":"accepted"}]}',
            },
        ]
    )
    assert "t1" in status.text and "accepted" in status.text
    fallback = await complete([{"role": "user", "content": "hello"}])
    assert fallback.text.startswith("I can search, book, track and cancel rides.")
