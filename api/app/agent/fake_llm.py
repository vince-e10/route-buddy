import json
import re
from uuid import uuid4

from app.models import CANCELLABLE_STATUSES

from .llm import LLMResponse, ToolCall


class FakeLLM:
    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        user_index = max(
            index for index, message in enumerate(messages) if message.get("role") == "user"
        )
        user_text = messages[user_index]["content"]
        lowered = user_text.lower()
        recent = messages[user_index + 1 :]

        if " from " in lowered and " to " in lowered:
            match = re.search(r"\sfrom\s(.+?)\sto\s(.+)$", user_text, re.IGNORECASE)
            pickup, dropoff = match.groups()
            results = self._tool_results(recent)
            if not results:
                return self._call("search_places", {"query": pickup.strip()}, "search_pickup")
            if len(results) == 1:
                return self._call("search_places", {"query": dropoff.strip()}, "search_dropoff")
            if len(results) == 2:
                return self._call(
                    "get_quotes",
                    {
                        "pickup_place_id": results[0]["places"][0]["place_id"],
                        "dropoff_place_id": results[1]["places"][0]["place_id"],
                    },
                    "get_quotes",
                )
            return LLMResponse(
                text="Here are your options. Reply 'book <product>' to book.",
                tool_calls=[],
            )

        if lowered.startswith("book"):
            if self._called(recent, "book_ride"):
                return LLMResponse(text="Please confirm in the card above.", tool_calls=[])
            quotes = self._latest_result(messages, "quotes").get("quotes", [])
            cheapest = min(quotes, key=self._price)
            return self._call("book_ride", {"fare_id": cheapest["fare_id"]}, "book_ride")

        if "cancel" in lowered:
            if self._called(recent, "cancel_ride"):
                return LLMResponse(text="Please confirm the cancellation.", tool_calls=[])
            trips_result = self._latest_result(recent, "trips")
            if not trips_result:
                return self._call("list_session_trips", {}, "list_session_trips")
            cancellable = [
                trip
                for trip in trips_result["trips"]
                if trip["status"] in {status.value for status in CANCELLABLE_STATUSES}
            ]
            trip = max(cancellable, key=lambda item: item["created_at"])
            return self._call("cancel_ride", {"trip_id": trip["trip_id"]}, "cancel_ride")

        if "status" in lowered:
            trips_result = self._latest_result(recent, "trips")
            if not trips_result:
                return self._call("list_session_trips", {}, "list_session_trips")
            text = ", ".join(
                f"{trip['trip_id']}: {trip['status']}" for trip in trips_result["trips"]
            )
            return LLMResponse(text=text or "No trips found.", tool_calls=[])

        return LLMResponse(
            text=(
                "I can search, book, track and cancel rides. Try: take me from Changi "
                "Airport to Marina Bay Sands."
            ),
            tool_calls=[],
        )

    @staticmethod
    def _call(name: str, arguments: dict, prefix: str) -> LLMResponse:
        return LLMResponse(
            text=None,
            tool_calls=[
                ToolCall(
                    id=f"{prefix}_{uuid4().hex[:8]}",
                    name=name,
                    arguments=json.dumps(arguments),
                )
            ],
        )

    @staticmethod
    def _tool_results(messages: list[dict]) -> list[dict]:
        results = []
        for message in messages:
            if message.get("role") != "tool":
                continue
            try:
                results.append(json.loads(message["content"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return results

    @classmethod
    def _latest_result(cls, messages: list[dict], key: str) -> dict:
        for result in reversed(cls._tool_results(messages)):
            if key in result:
                return result
        return {}

    @staticmethod
    def _called(messages: list[dict], name: str) -> bool:
        return any(
            call.get("function", {}).get("name") == name
            for message in messages
            for call in message.get("tool_calls", [])
        )

    @staticmethod
    def _price(quote: dict) -> float:
        if "price_value" in quote:
            return float(quote["price_value"])
        match = re.search(r"\d+(?:\.\d+)?", quote["price_display"])
        return float(match.group()) if match else float("inf")
