from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.publishing import publisher
from app.agent.rate_limit import RateLimiter
from app.agent.session_locks import session_lock
from app.models import ActionLogEntry, GuestProfile, Quote, Session, Trip
from app.providers.uber import ProviderError

router = APIRouter()
_limiter = RateLimiter(10, 60)


class ConfirmRequest(BaseModel):
    token: str
    decision: Literal["confirm", "dismiss"]


@router.post("/confirm")
async def confirm(request: ConfirmRequest) -> dict:
    from app import deps

    if not _limiter.allow(request.token):
        raise HTTPException(status_code=429, detail="Too many confirmation attempts.")
    action = await deps.pending_repo.claim(request.token)
    if action is None:
        await _log(
            deps.action_log_repo,
            "unknown",
            "unknown",
            "verified",
            "user",
            "confirm",
            {"result": "expired_or_unknown_token"},
        )
        return {"result": "expired", "trip_id": None}
    if request.decision == "dismiss":
        await _log(
            deps.action_log_repo,
            action.session_id,
            action.correlation_id,
            "outcome",
            "user",
            action.action_type,
            {"result": "aborted_by_user"},
        )
        await publisher.publish(
            action.session_id,
            {
                "type": "confirmation_resolved",
                "token": action.token,
                "result": "dismissed",
                "trip_id": None,
            },
        )
        return {"result": "dismissed", "trip_id": None}

    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "verified",
        "user",
        action.action_type,
        {"result": "claimed"},
    )
    if action.action_type == "book":
        return await _book(action, deps, publisher)
    return await _cancel(action, deps, publisher)


async def _book(action, deps, publisher) -> dict:
    quote = Quote.model_validate(action.payload["quote"])
    guest = GuestProfile(
        first_name=deps.settings.rider_first_name,
        last_name=deps.settings.rider_last_name,
        phone_number=deps.settings.rider_phone,
    )
    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "executed",
        "system",
        "book_ride",
        {
            "endpoint": "POST /v1/guests/trips",
            "product_id": quote.product_id,
            "fare_id": quote.fare_id,
        },
    )
    try:
        state = await deps.provider.book(quote, guest)
    except ProviderError as error:
        return await _failed(action, deps, publisher, "book_ride", error.code)
    now = datetime.now(timezone.utc)
    trip = Trip(
        trip_id=f"uber:{state.provider_request_id}",
        provider="uber",
        provider_request_id=state.provider_request_id,
        session_id=action.session_id,
        status=state.status,
        quote=quote,
        driver=state.driver,
        created_at=now,
        updated_at=now,
    )
    await deps.trip_repo.put(trip)
    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "outcome",
        "system",
        "book_ride",
        {"result": "booked", "trip_id": trip.trip_id},
    )
    await _resolved(action, publisher, "executed", trip)
    try:
        async with session_lock(action.session_id):
            session = await deps.session_repo.get(action.session_id) or Session(
                session_id=action.session_id,
                created_at=now,
                updated_at=now,
                expires_at=int(now.timestamp()) + 86400,
            )
            session.messages.append(
                {
                    "role": "system",
                    "content": (
                        f"Booking executed: trip {trip.trip_id} status {trip.status.value}"
                    ),
                }
            )
            await deps.session_repo.put(session)
    except Exception:
        pass
    return {"result": "executed", "trip_id": trip.trip_id}


async def _cancel(action, deps, publisher) -> dict:
    trip = await deps.trip_repo.get(action.payload["trip_id"])
    if trip is None or trip.session_id != action.session_id:
        return await _failed(action, deps, publisher, "cancel_ride", "trip_not_found")
    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "executed",
        "system",
        "cancel_ride",
        {
            "endpoint": f"DELETE /v1/guests/trips/{trip.provider_request_id}",
            "trip_id": trip.trip_id,
        },
    )
    try:
        state = await deps.provider.cancel(trip.provider_request_id)
    except ProviderError as error:
        return await _failed(action, deps, publisher, "cancel_ride", error.code)
    trip = trip.model_copy(
        update={
            "status": state.status,
            "driver": state.driver,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    await deps.trip_repo.put(trip)
    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "outcome",
        "system",
        "cancel_ride",
        {"result": "cancelled", "trip_id": trip.trip_id, "status": trip.status.value},
    )
    await _resolved(action, publisher, "executed", trip)
    return {"result": "executed", "trip_id": trip.trip_id}


async def _failed(action, deps, publisher, tool: str, code: str) -> dict:
    await _log(
        deps.action_log_repo,
        action.session_id,
        action.correlation_id,
        "outcome",
        "system",
        tool,
        {"result": "failed", "code": code},
    )
    await publisher.publish(
        action.session_id,
        {
            "type": "confirmation_resolved",
            "token": action.token,
            "result": "failed",
            "trip_id": None,
        },
    )
    return {"result": "failed", "trip_id": None}


async def _resolved(action, publisher, result: str, trip: Trip) -> None:
    await publisher.publish(
        action.session_id,
        {
            "type": "confirmation_resolved",
            "token": action.token,
            "result": result,
            "trip_id": trip.trip_id,
        },
    )
    await publisher.publish(action.session_id, _trip_update(trip))


def _trip_update(trip: Trip) -> dict:
    return {
        "type": "trip_update",
        "trip_id": trip.trip_id,
        "status": trip.status.value,
        "driver": trip.driver.model_dump() if trip.driver else None,
        "product_name": trip.quote.product_name,
        "price_display": trip.quote.price_display,
    }


async def _log(repo, session_id, correlation_id, phase, actor, tool, payload) -> None:
    await repo.append(
        ActionLogEntry(
            session_id=session_id,
            entry_key="",
            correlation_id=correlation_id,
            phase=phase,
            actor=actor,
            tool=tool,
            payload=payload,
            ts=datetime.now(timezone.utc),
        )
    )
