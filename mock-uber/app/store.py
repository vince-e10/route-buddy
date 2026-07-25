import asyncio
import time
import uuid
from dataclasses import dataclass

from app.models import CANCELLABLE_STATUSES, LEGAL_TRANSITIONS, TripStatus


@dataclass
class Fare:
    product_id: str
    value: float
    expires_at: int
    pickup: dict
    dropoff: dict
    surge_multiplier: float


@dataclass
class TripRecord:
    request_id: str
    product_id: str
    fare_id: str
    pickup: dict
    dropoff: dict
    guest: dict
    fare_value: float
    surge_multiplier: float
    scenario: str | None
    status: TripStatus = TripStatus.processing
    driver: dict | None = None


class Store:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.fares: dict[str, Fare] = {}
        self.trips: dict[str, TripRecord] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.no_drivers = False
        self.driver_cancel = False
        self.surge_multiplier = 1.0
        self.driver_index = 0

    async def issue_fare(self, product_id, value, pickup, dropoff, surge_multiplier):
        fare_id = f"fare_{uuid.uuid4().hex}"
        fare = Fare(product_id, value, int(time.time()) + 300, pickup, dropoff, surge_multiplier)
        async with self.lock:
            self.fares[fare_id] = fare
        return fare_id, fare

    async def get_fare(self, fare_id):
        async with self.lock:
            return self.fares.get(fare_id)

    async def current_surge(self):
        async with self.lock:
            return self.surge_multiplier

    async def create_trip(self, product_id, fare_id, pickup, dropoff, guest, surge_multiplier):
        async with self.lock:
            scenario = "no_drivers" if self.no_drivers else "driver_cancel" if self.driver_cancel else None
            self.no_drivers = False
            self.driver_cancel = False
            fare = self.fares[fare_id]
            request_id = f"req_{uuid.uuid4().hex}"
            trip = TripRecord(
                request_id, product_id, fare_id, pickup, dropoff, guest, fare.value, surge_multiplier, scenario
            )
            self.trips[request_id] = trip
            return trip

    async def get_trip(self, request_id):
        async with self.lock:
            return self.trips.get(request_id)

    async def transition_trip(self, request_id, status, driver=None):
        async with self.lock:
            trip = self.trips[request_id]
            if status not in LEGAL_TRANSITIONS[trip.status]:
                raise ValueError(f"illegal transition {trip.status.value}->{status.value}")
            trip.status = status
            if driver is not None:
                trip.driver = driver
            return trip

    async def cancel_trip(self, request_id):
        async with self.lock:
            trip = self.trips.get(request_id)
            if trip is None or trip.status not in CANCELLABLE_STATUSES:
                return None
            trip.status = TripStatus.rider_canceled
            return trip

    async def next_driver(self):
        drivers = [
            {"name": "Aisha Tan", "rating": 4.6},
            {"name": "Ben Lim", "rating": 4.7},
            {"name": "Cheryl Lee", "rating": 4.8},
            {"name": "Daniel Ong", "rating": 4.9},
            {"name": "Evelyn Goh", "rating": 5.0},
        ]
        async with self.lock:
            driver = drivers[self.driver_index % len(drivers)]
            self.driver_index += 1
            return driver

    async def set_task(self, request_id, task):
        async with self.lock:
            self.tasks[request_id] = task

    async def task_for(self, request_id):
        async with self.lock:
            return self.tasks.get(request_id)

    async def is_terminal(self, request_id):
        trip = await self.get_trip(request_id)
        return trip is None or not LEGAL_TRANSITIONS[trip.status]

    async def apply_scenario(self, scenario, surge_multiplier=None):
        async with self.lock:
            if scenario == "no_drivers":
                self.no_drivers = True
            elif scenario == "driver_cancel":
                self.driver_cancel = True
            elif scenario == "surge":
                self.surge_multiplier = surge_multiplier if surge_multiplier is not None else 2.0
            elif scenario == "reset":
                self.no_drivers = False
                self.driver_cancel = False
                self.surge_multiplier = 1.0

    async def cancel_and_drain_tasks(self):
        async with self.lock:
            tasks = list(self.tasks.values())
            self.tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
