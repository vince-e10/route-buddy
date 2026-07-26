from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import Settings, settings


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None


class LLMResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]
    model: str | None = None
    provider: str | None = None
    usage: LLMUsage | None = None


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> LLMResponse: ...


class LLMError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenRouterClient:
    def __init__(self, config: Settings = settings) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.openrouter_base_url.rstrip("/"),
            timeout=60,
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> LLMResponse:
        body = {
            "model": model or self._config.openrouter_model_primary,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 1024,
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        if model is None:
            body["models"] = [
                self._config.openrouter_model_primary,
                self._config.openrouter_model_fallback,
            ]
        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx.TimeoutException:
            raise LLMError("OpenRouter request timed out") from None
        except httpx.HTTPError:
            raise LLMError("OpenRouter request failed") from None
        if not response.is_success:
            raise LLMError(
                f"OpenRouter request failed ({response.status_code})",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            calls = [
                ToolCall(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=call["function"]["arguments"],
                )
                for call in message.get("tool_calls", [])
            ]
            return LLMResponse(
                text=message.get("content"),
                tool_calls=calls,
                model=payload.get("model"),
                provider=payload.get("provider"),
                usage=payload.get("usage"),
            )
        except (KeyError, TypeError, ValueError):
            raise LLMError("OpenRouter returned an invalid response") from None
