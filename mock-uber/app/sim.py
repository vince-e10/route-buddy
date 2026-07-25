import asyncio
import logging
import os
import time
import uuid

import httpx

from app.models import TripStatus, WebhookEvent


logger = logging.getLogger(__name__)


class Simulator:
    def __init__(self, store):
        self.store = store
        self._observed: dict[str, asyncio.Event] = {}

    async def start(self, trip):
        if os.getenv("MOCK_DETERMINISTIC") == "1":
            self._observed[trip.request_id] = asyncio.Event()
        task = asyncio.create_task(self._run(trip.request_id, trip.scenario))
        await self.store.set_task(trip.request_id, task)

    async def cancel(self, request_id):
        task = await self.store.task_for(request_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def observe(self, request_id):
        event = self._observed.get(request_id)
        if event is not None:
            event.set()

    async def _delay(self, seconds, request_id):
        if os.getenv("MOCK_DETERMINISTIC") == "1":
            event = self._observed.get(request_id)
            if event is not None:
                try:
                    await asyncio.wait_for(event.wait(), timeout=0.05)
                except TimeoutError:
                    pass
                event.clear()
            await asyncio.sleep(0)
            return
        speed = float(os.getenv("SIM_SPEED", "1.0"))
        await asyncio.sleep(seconds / (speed if speed > 0 else 1.0))

    async def _advance(self, request_id, status, driver=None):
        if await self.store.is_terminal(request_id):
            return False
        try:
            trip = await self.store.transition_trip(request_id, status, driver)
        except ValueError:
            logger.exception("simulator attempted an illegal transition")
            raise
        await self.emit(trip)
        return True

    async def _run(self, request_id, scenario):
        try:
            await self._delay(3, request_id)
            if scenario == "no_drivers":
                await self._advance(request_id, TripStatus.no_drivers_available)
                return
            if not await self._advance(request_id, TripStatus.accepted, await self.store.next_driver()):
                return
            await self._delay(8, request_id)
            if scenario == "driver_cancel":
                await self._advance(request_id, TripStatus.driver_canceled)
                return
            if not await self._advance(request_id, TripStatus.arriving):
                return
            await self._delay(10, request_id)
            if not await self._advance(request_id, TripStatus.in_progress):
                return
            await self._delay(20, request_id)
            await self._advance(request_id, TripStatus.completed)
        except asyncio.CancelledError:
            return

    async def emit(self, trip):
        payload = WebhookEvent(
            event_id=f"evt_{uuid.uuid4().hex}",
            event_time=int(time.time()),
            event_type="guests.trips.status_changed",
            resource_href=f"http://mock-uber:8001/v1/guests/trips/{trip.request_id}",
            meta={
                "user_id": "mock-user",
                "org_uuid": os.getenv("UBER_ORG_UUID", "mock-org-uuid"),
                "resource_id": trip.request_id,
                "status": trip.status.value,
            },
        ).model_dump(mode="json")
        await self.deliver_webhook(payload)

    async def _post_webhook(self, payload):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                os.getenv("WEBHOOK_TARGET_URL", "http://api:8000/webhooks/uber"),
                json=payload,
                headers={"X-Webhook-Secret": os.getenv("WEBHOOK_SHARED_SECRET", "")},
            )
        return 200 <= response.status_code < 300

    async def deliver_webhook(self, payload):
        for attempt in range(3):
            try:
                if await self._post_webhook(payload):
                    return
            except (httpx.HTTPError, OSError):
                pass
            if attempt < 2:
                await asyncio.sleep((1, 2)[attempt])
        logger.warning("dropping webhook after three attempts", extra={"event_id": payload["event_id"]})
