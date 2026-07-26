import json
import re
from uuid import uuid4

from .llm import LLMResponse, ToolCall


class FakeLLM:
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> LLMResponse:
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
                text="Here are your options. Use Select on the exact ride option card.",
                tool_calls=[],
            )

        if lowered.startswith("book"):
            return LLMResponse(
                text="Use Select on the exact ride option card you want.",
                tool_calls=[],
            )

        if "cancel" in lowered:
            trips_result = self._latest_result(recent, "trips")
            if not trips_result:
                return self._call("list_session_trips", {}, "list_session_trips")
            return LLMResponse(
                text="Use Select cancellation on the exact trip card you want.",
                tool_calls=[],
            )

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
