from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import Settings, settings


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class LLMResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]


class LLMClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class LLMError(Exception):
    pass


class OpenRouterClient:
    def __init__(self, config: Settings = settings) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.openrouter_base_url.rstrip("/"),
            timeout=60,
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        )

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body = {
            "model": self._config.openrouter_model_primary,
            "models": [
                self._config.openrouter_model_primary,
                self._config.openrouter_model_fallback,
            ],
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 1024,
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx.TimeoutException:
            raise LLMError("OpenRouter request timed out") from None
        except httpx.HTTPError:
            raise LLMError("OpenRouter request failed") from None
        if not response.is_success:
            raise LLMError(f"OpenRouter request failed ({response.status_code})")
        try:
            message = response.json()["choices"][0]["message"]
            calls = [
                ToolCall(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=call["function"]["arguments"],
                )
                for call in message.get("tool_calls", [])
            ]
            return LLMResponse(text=message.get("content"), tool_calls=calls)
        except (KeyError, TypeError, ValueError):
            raise LLMError("OpenRouter returned an invalid response") from None
