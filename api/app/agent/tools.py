import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from app.geocode.base import Geocoder
from app.geocode.onemap import GeocodeError
from app.models import (
    CANCELLABLE_STATUSES,
    ActionLogEntry,
    PendingAction,
    Session,
)
from app.providers.base import RideProvider
from app.providers.uber import ProviderError
from app.storage import ActionLogRepo, PendingActionRepo, SessionRepo, TripRepo
from app.ws.publisher import WsPublisher


@dataclass
class ToolContext:
    session_repo: SessionRepo
    trip_repo: TripRepo
    action_log_repo: ActionLogRepo
    pending_repo: PendingActionRepo
    provider: RideProvider
    geocoder: Geocoder
    publisher: WsPublisher
    correlation_id: str
    actor: Literal["llm", "user"]


async def _log(
    ctx: ToolContext,
    session_id: str,
    correlation_id: str,
    phase: str,
    actor: str,
    tool: str | None,
    payload: dict,
) -> None:
    await ctx.action_log_repo.append(
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


async def _requested(
    ctx: ToolContext, session: Session, correlation_id: str, tool: str, args: dict
) -> None:
    await _log(
        ctx, session.session_id, correlation_id, "requested", ctx.actor, tool, args
    )


async def _rejected(
    ctx: ToolContext, session: Session, correlation_id: str, tool: str, reason: str
) -> dict:
    await _log(
        ctx,
        session.session_id,
        correlation_id,
        "verified",
        "system",
        tool,
        {"result": "rejected", "reason": reason},
    )
    return {"error": reason}


async def handle_search_places(session: Session, args: dict, ctx: ToolContext) -> dict:
    await _requested(ctx, session, ctx.correlation_id, "search_places", args)
    places = []
    try:
        found = await ctx.geocoder.search(args["query"])
    except GeocodeError as error:
        return await _read_error(ctx, session, "search_places", error.detail)
    for place in found:
        value = place.model_copy(update={"place_id": f"plc_{uuid4().hex[:8]}"})
        session.places[value.place_id] = value
        places.append(
            {
                "place_id": value.place_id,
                "name": value.name,
                "address": value.address,
                "postal": value.postal,
            }
        )
    result = {"places": places}
    await _log(
        ctx,
        session.session_id,
        ctx.correlation_id,
        "outcome",
        "llm",
        "search_places",
        {"count": len(places)},
    )
    return result


async def handle_get_quotes(session: Session, args: dict, ctx: ToolContext) -> dict:
    await _requested(ctx, session, ctx.correlation_id, "get_quotes", args)
    for key in ("pickup_place_id", "dropoff_place_id"):
        place_id = args[key]
        if place_id not in session.places:
            return await _rejected(
                ctx,
                session,
                ctx.correlation_id,
                "get_quotes",
                f"unknown place_id {place_id}; call search_places first",
            )
    pickup = session.places[args["pickup_place_id"]]
    dropoff = session.places[args["dropoff_place_id"]]
    try:
        quotes = await ctx.provider.get_quotes(
            pickup.location, dropoff.location, pickup.name, dropoff.name
        )
    except ProviderError as error:
        return await _read_error(ctx, session, "get_quotes", error.detail, error.code)
    session.quotes = {quote.fare_id: quote for quote in quotes}
    await ctx.publisher.publish(
        session.session_id,
        {
            "type": "quotes",
            "items": [quote.model_dump(mode="json") for quote in quotes],
        },
    )
    result = {
        "quotes": [
            {
                "fare_id": quote.fare_id,
                "product_name": quote.product_name,
                "price_display": quote.price_display,
                "pickup_eta_minutes": quote.pickup_eta_minutes,
                "duration_minutes": quote.duration_minutes,
            }
            for quote in quotes
        ]
    }
    await _log(
        ctx,
        session.session_id,
        ctx.correlation_id,
        "outcome",
        "llm",
        "get_quotes",
        {"count": len(quotes), "fare_ids": list(session.quotes)},
    )
    return result


async def handle_book_ride(session: Session, args: dict, ctx: ToolContext) -> dict:
    correlation_id = ctx.correlation_id
    await _requested(ctx, session, correlation_id, "book_ride", args)
    quote = session.quotes.get(args["fare_id"])
    if quote is None:
        return await _rejected(
            ctx,
            session,
            correlation_id,
            "book_ride",
            "That ride option is no longer current. Select an option from the latest quote cards.",
        )
    if quote.expires_at <= datetime.now(timezone.utc):
        return await _rejected(
            ctx,
            session,
            correlation_id,
            "book_ride",
            "That quote expired. Search for fresh ride options and select again.",
        )
    action = PendingAction(
        token=secrets.token_urlsafe(32),
        session_id=session.session_id,
        action_type="book",
        payload={"quote": quote.model_dump(mode="json")},
        correlation_id=correlation_id,
        created_at=datetime.now(timezone.utc),
        expires_at=int(quote.expires_at.timestamp()),
    )
    await ctx.pending_repo.put(action)
    await _log(
        ctx,
        session.session_id,
        correlation_id,
        "verified",
        "system",
        "book_ride",
        {"result": "token_created"},
    )
    await ctx.publisher.publish(
        session.session_id,
        {
            "type": "confirmation_request",
            "token": action.token,
            "action": "book",
            "summary": _summary(quote, None),
        },
    )
    return {"status": "pending_user_confirmation"}


async def handle_get_trip_status(session: Session, args: dict, ctx: ToolContext) -> dict:
    await _requested(ctx, session, ctx.correlation_id, "get_trip_status", args)
    trip = await ctx.trip_repo.get(args["trip_id"])
    if trip is None or trip.session_id != session.session_id:
        return await _rejected(
            ctx,
            session,
            ctx.correlation_id,
            "get_trip_status",
            "trip not found in this session",
        )
    try:
        state = await ctx.provider.get_trip(trip.provider_request_id)
    except ProviderError as error:
        return await _read_error(
            ctx, session, "get_trip_status", error.detail, error.code
        )
    if state.status != trip.status or state.driver != trip.driver:
        trip = trip.model_copy(
            update={
                "status": state.status,
                "driver": state.driver,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        await ctx.trip_repo.put(trip)
    result = {
        "trip_id": trip.trip_id,
        "status": trip.status.value,
        "product_name": trip.quote.product_name,
        "price_display": trip.quote.price_display,
        "driver_name": trip.driver.name if trip.driver else None,
    }
    await _log(
        ctx,
        session.session_id,
        ctx.correlation_id,
        "outcome",
        "llm",
        "get_trip_status",
        result,
    )
    return result


async def handle_list_session_trips(session: Session, args: dict, ctx: ToolContext) -> dict:
    await _requested(ctx, session, ctx.correlation_id, "list_session_trips", args)
    trips = await ctx.trip_repo.list_by_session(session.session_id)
    result = {
        "trips": [
            {
                "trip_id": trip.trip_id,
                "status": trip.status.value,
                "product_name": trip.quote.product_name,
                "pickup_label": trip.quote.pickup_label,
                "dropoff_label": trip.quote.dropoff_label,
                "created_at": trip.created_at.isoformat(),
            }
            for trip in trips
        ]
    }
    await _log(
        ctx,
        session.session_id,
        ctx.correlation_id,
        "outcome",
        "llm",
        "list_session_trips",
        {"count": len(trips)},
    )
    return result


async def handle_cancel_ride(session: Session, args: dict, ctx: ToolContext) -> dict:
    correlation_id = ctx.correlation_id
    await _requested(ctx, session, correlation_id, "cancel_ride", args)
    trip = await ctx.trip_repo.get(args["trip_id"])
    if trip is None or trip.session_id != session.session_id:
        return await _rejected(
            ctx,
            session,
            correlation_id,
            "cancel_ride",
            "That trip was not found in this session. Refresh your trip list and select again.",
        )
    if trip.status not in CANCELLABLE_STATUSES:
        return await _rejected(
            ctx,
            session,
            correlation_id,
            "cancel_ride",
            "That trip is not cancellable.",
        )
    action = PendingAction(
        token=secrets.token_urlsafe(32),
        session_id=session.session_id,
        action_type="cancel",
        payload={"trip_id": trip.trip_id},
        correlation_id=correlation_id,
        created_at=datetime.now(timezone.utc),
        expires_at=int(time.time()) + 120,
    )
    await ctx.pending_repo.put(action)
    await _log(
        ctx,
        session.session_id,
        correlation_id,
        "verified",
        "system",
        "cancel_ride",
        {"result": "token_created"},
    )
    await ctx.publisher.publish(
        session.session_id,
        {
            "type": "confirmation_request",
            "token": action.token,
            "action": "cancel",
            "summary": _summary(
                trip.quote,
                trip.trip_id,
                datetime.fromtimestamp(action.expires_at, timezone.utc),
            ),
        },
    )
    return {"status": "pending_user_confirmation"}


def _summary(
    quote, trip_id: str | None, expires_at: datetime | None = None
) -> dict:
    return {
        "product_name": quote.product_name,
        "price_display": quote.price_display,
        "pickup_label": quote.pickup_label,
        "dropoff_label": quote.dropoff_label,
        "expires_at": (expires_at or quote.expires_at).isoformat(),
        "trip_id": trip_id,
    }


async def _read_error(
    ctx: ToolContext,
    session: Session,
    tool: str,
    detail: str,
    code: str | None = None,
) -> dict:
    payload = {"error": detail}
    if code:
        payload["code"] = code
    await _log(
        ctx,
        session.session_id,
        ctx.correlation_id,
        "outcome",
        "llm",
        tool,
        payload,
    )
    return {"error": detail}


HANDLERS = {
    "search_places": handle_search_places,
    "get_quotes": handle_get_quotes,
    "get_trip_status": handle_get_trip_status,
    "list_session_trips": handle_list_session_trips,
}
