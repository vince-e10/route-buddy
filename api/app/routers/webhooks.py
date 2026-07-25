import hmac
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from app.agent.publishing import publisher
from app.models import ActionLogEntry, TripStatus
router = APIRouter()


class WebhookMeta(BaseModel):
    user_id: str
    org_uuid: str
    resource_id: str
    status: TripStatus


class UberWebhook(BaseModel):
    event_id: str
    event_time: int
    event_type: str
    resource_href: str
    meta: WebhookMeta


@router.post("/webhooks/uber", status_code=204)
async def uber_webhook(
    payload: UberWebhook,
    x_webhook_secret: str | None = Header(default=None),
) -> Response:
    from app import deps

    configured = deps.settings.webhook_shared_secret
    if not configured:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured.")
    if x_webhook_secret is None or not hmac.compare_digest(x_webhook_secret, configured):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    trip_id = f"uber:{payload.meta.resource_id}"
    before = await deps.trip_repo.get(trip_id)
    trip = await deps.trip_repo.apply_status_event(
        trip_id, payload.event_id, payload.meta.status, None
    )
    if trip is None:
        await _log(
            deps.action_log_repo,
            before.session_id if before else "unknown",
            payload,
            False,
            "duplicate_or_unknown",
        )
        return Response(status_code=204)

    if payload.meta.status in {
        TripStatus.accepted,
        TripStatus.driver_redispatched,
    }:
        try:
            state = await deps.provider.get_trip(payload.meta.resource_id)
            enriched = trip.model_copy(
                update={
                    "driver": state.driver,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            await deps.trip_repo.put(enriched)
        except Exception:
            pass
        else:
            trip = enriched
    await _log(deps.action_log_repo, trip.session_id, payload, True, None)
    await publisher.publish(
        trip.session_id,
        {
            "type": "trip_update",
            "trip_id": trip.trip_id,
            "status": trip.status.value,
            "driver": trip.driver.model_dump() if trip.driver else None,
            "product_name": trip.quote.product_name,
            "price_display": trip.quote.price_display,
        },
    )
    return Response(status_code=204)


async def _log(repo, session_id, payload, applied, reason) -> None:
    value = {
        "event_id": payload.event_id,
        "status": payload.meta.status.value,
        "applied": applied,
    }
    if reason:
        value["reason"] = reason
    await repo.append(
        ActionLogEntry(
            session_id=session_id,
            entry_key="",
            correlation_id=f"act_{uuid4().hex[:12]}",
            phase="outcome",
            actor="webhook",
            tool=None,
            payload=value,
            ts=datetime.now(timezone.utc),
        )
    )
