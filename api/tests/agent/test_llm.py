import httpx
import pytest
import respx

from app.agent.llm import LLMError, OpenRouterClient


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_payload_and_response(config):
    route = respx.post(f"{config.openrouter_base_url}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "provider/model",
                "provider": "provider-name",
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                    "cost": 0.0004,
                },
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "search_places", "arguments": '{"query":"x"}'},
                                }
                            ],
                        }
                    }
                ]
            },
        )
    )
    client = OpenRouterClient(config)
    result = await client.complete([{"role": "user", "content": "x"}], [{"type": "function"}])

    assert result.text == "ok"
    assert result.tool_calls[0].name == "search_places"
    assert result.model == "provider/model"
    assert result.provider == "provider-name"
    assert result.usage.total_tokens == 15
    assert result.usage.cost == 0.0004
    request = route.calls[0].request
    body = __import__("json").loads(request.content)
    assert body["models"] == [
        config.openrouter_model_primary,
        config.openrouter_model_fallback,
    ]
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert body["tool_choice"] == "auto"
    assert request.headers["authorization"] == f"Bearer {config.openrouter_api_key}"


@pytest.mark.asyncio
@respx.mock
async def test_explicit_model_is_pinned_without_fallbacks(config):
    route = respx.post(f"{config.openrouter_base_url}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )
    )

    await OpenRouterClient(config).complete([], [], model="provider/pinned")

    body = __import__("json").loads(route.calls[0].request.content)
    assert body["model"] == "provider/pinned"
    assert "models" not in body
    assert body["provider"]["data_collection"] == "deny"


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_non_2xx_and_timeout_raise_llm_error(config):
    route = respx.post(f"{config.openrouter_base_url}/chat/completions")
    route.mock(return_value=httpx.Response(500, text="secret must not leak"))
    client = OpenRouterClient(config)
    with pytest.raises(LLMError, match="request failed") as raised:
        await client.complete([], [])
    assert raised.value.status_code == 500
    assert "secret must not leak" not in str(raised.value)

    route.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(LLMError, match="timed out") as raised:
        await client.complete([], [])
    assert raised.value.status_code is None
