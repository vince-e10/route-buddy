import json
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.config import settings
from app.geocode.base import Geocoder
from app.logging_setup import RedactionFilter
from app.models import ActionLogEntry, Session
from app.providers.base import RideProvider
from app.storage import ActionLogRepo, PendingActionRepo, SessionRepo, TripRepo

from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT
from .publishing import publisher
from .rate_limit import RateLimiter
from .session_locks import session_lock
from .tool_contracts import ARG_MODELS, session_tool_schemas
from .tools import HANDLERS, ToolContext


class AgentServiceImpl:
    def __init__(
        self,
        *,
        session_repo: SessionRepo,
        trip_repo: TripRepo,
        action_log_repo: ActionLogRepo,
        pending_repo: PendingActionRepo,
        provider: RideProvider,
        geocoder: Geocoder,
        llm: LLMClient,
        fallback_model: str,
    ) -> None:
        self._session_repo = session_repo
        self._trip_repo = trip_repo
        self._action_log_repo = action_log_repo
        self._pending_repo = pending_repo
        self._provider = provider
        self._geocoder = geocoder
        self._llm = llm
        self._fallback_model = fallback_model
        self._redact = RedactionFilter(
            settings.secret_values
            + [
                settings.rider_first_name,
                settings.rider_last_name,
                settings.rider_phone,
            ]
        ).redact_json
        # ponytail: in-memory rate limiter, single instance; move to DynamoDB counters if we ever scale out
        self._limiter = RateLimiter(20, 60)

    async def handle_user_message(self, session_id: str, text: str) -> None:
        if not self._limiter.allow(session_id):
            await publisher.publish(
                session_id,
                {
                    "type": "error",
                    "message": "You're sending messages too quickly, give me a moment.",
                },
            )
            return
        async with session_lock(session_id):
            await self._handle_locked(session_id, text)

    async def _handle_locked(self, session_id: str, text: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            stored = await self._session_repo.get(session_id)
        except Exception:
            await publisher.publish(
                session_id,
                {
                    "type": "error",
                    "message": "The assistant is unavailable right now, try again shortly.",
                },
            )
            return
        session = stored or Session(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            expires_at=int(now.timestamp()) + 86400,
        )
        session.messages.append({"role": "user", "content": text})
        correlation_id = f"act_{uuid4().hex[:12]}"
        ctx = ToolContext(
            session_repo=self._session_repo,
            trip_repo=self._trip_repo,
            action_log_repo=self._action_log_repo,
            pending_repo=self._pending_repo,
            provider=self._provider,
            geocoder=self._geocoder,
            publisher=publisher,
            correlation_id=correlation_id,
        )
        correction_pending = False
        correction_used = False
        try:
            for _ in range(6):
                trips = await self._trip_repo.list_by_session(session.session_id)
                schemas = session_tool_schemas(session, trips)
                messages = [{"role": "system", "content": SYSTEM_PROMPT}] + session.messages
                was_correction = correction_pending
                if was_correction:
                    response = await self._llm.complete(
                        messages, schemas, model=self._fallback_model
                    )
                    correction_pending = False
                else:
                    response = await self._llm.complete(messages, schemas)
                if response.tool_calls:
                    session.messages.append(
                        {
                            "role": "assistant",
                            "content": response.text,
                            "tool_calls": [
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {
                                        "name": call.name,
                                        "arguments": call.arguments,
                                    },
                                }
                                for call in response.tool_calls
                            ],
                        }
                    )
                    structurally_rejected = len(response.tool_calls) != 1
                    if structurally_rejected:
                        await self._invalid(
                            session, response.tool_calls, ctx, "multiple_tool_calls"
                        )
                        results = [
                            (
                                call,
                                {
                                    "error": (
                                        "multiple tool calls are not supported, "
                                        "please retry with exactly one tool"
                                    )
                                },
                            )
                            for call in response.tool_calls
                        ]
                    else:
                        call = response.tool_calls[0]
                        result, structurally_rejected = await self._dispatch(
                            session, call, ctx, schemas
                        )
                        results = [(call, result)]
                    for call, result in results:
                        session.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(result),
                            }
                        )
                    if structurally_rejected:
                        if correction_used:
                            await publisher.publish(
                                session_id,
                                {
                                    "type": "assistant_msg",
                                    "text": "Sorry, I got stuck - could you rephrase?",
                                },
                            )
                            break
                        correction_pending = True
                        correction_used = True
                    continue
                if was_correction and not response.text:
                    await publisher.publish(
                        session_id,
                        {
                            "type": "assistant_msg",
                            "text": "Sorry, I got stuck - could you rephrase?",
                        },
                    )
                    break
                if response.text is not None:
                    session.messages.append({"role": "assistant", "content": response.text})
                    await publisher.publish(
                        session_id, {"type": "assistant_msg", "text": response.text}
                    )
                    break
            else:
                await publisher.publish(
                    session_id,
                    {
                        "type": "assistant_msg",
                        "text": "Sorry, I got stuck - could you rephrase?",
                    },
                )
        except LLMError:
            await publisher.publish(
                session_id,
                {
                    "type": "error",
                    "message": "The assistant is unavailable right now, try again shortly.",
                },
            )
        except Exception:
            await publisher.publish(
                session_id,
                {
                    "type": "error",
                    "message": "The assistant is unavailable right now, try again shortly.",
                },
            )
        finally:
            try:
                await self._session_repo.put(session)
            except Exception:
                pass

    async def _dispatch(self, session, call, ctx, schemas) -> tuple[dict, bool]:
        supplied = {
            schema["function"]["name"]: schema["function"]["parameters"]
            for schema in schemas
        }
        if call.name not in supplied:
            await self._invalid(session, [call], ctx, "unknown_tool")
            return {"error": "unknown tool, please retry with an available tool"}, True
        try:
            raw_args = json.loads(call.arguments)
        except json.JSONDecodeError:
            await self._invalid(session, [call], ctx, "malformed_arguments")
            return {
                "error": "malformed tool arguments, please retry with valid JSON"
            }, True
        if call.name not in HANDLERS:
            await self._invalid(session, [call], ctx, "unknown_tool")
            return {"error": "unknown tool, please retry with an available tool"}, True
        try:
            args = ARG_MODELS[call.name].model_validate(raw_args).model_dump()
        except ValidationError:
            await self._invalid(session, [call], ctx, "invalid_arguments")
            return {
                "error": "invalid tool arguments, please retry with valid arguments"
            }, True
        if any(
            "enum" in property_schema and args.get(field) not in property_schema["enum"]
            for field, property_schema in supplied[call.name]["properties"].items()
        ):
            await self._invalid(session, [call], ctx, "invalid_arguments")
            return {
                "error": "invalid tool arguments, please retry with valid arguments"
            }, True
        return await HANDLERS[call.name](session, args, ctx), False

    async def _invalid(self, session, calls, ctx, error) -> None:
        tool = calls[0].name if len(calls) == 1 else None
        await self._action_log_repo.append(
            ActionLogEntry(
                session_id=session.session_id,
                entry_key="",
                correlation_id=ctx.correlation_id,
                phase="requested",
                actor="llm",
                tool=tool,
                payload={
                    "proposals": [
                        {
                            "name": call.name,
                            "arguments": self._redact(call.arguments)[:512],
                        }
                        for call in calls
                    ]
                },
                ts=datetime.now(timezone.utc),
            )
        )
        await self._action_log_repo.append(
            ActionLogEntry(
                session_id=session.session_id,
                entry_key="",
                correlation_id=ctx.correlation_id,
                phase="verified",
                actor="system",
                tool=tool,
                payload={"result": "rejected", "error": error},
                ts=datetime.now(timezone.utc),
            )
        )
