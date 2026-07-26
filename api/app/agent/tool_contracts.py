from pydantic import BaseModel, ConfigDict


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": "Search Singapore places (landmarks, buildings, postal codes) and return candidates with place_ids.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quotes",
            "description": "Get ride quotes between two previously searched places. Use place_ids returned by search_places.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pickup_place_id": {"type": "string"},
                    "dropoff_place_id": {"type": "string"},
                },
                "required": ["pickup_place_id", "dropoff_place_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_ride",
            "description": "Propose booking a quoted ride. Requires the user to confirm in the UI before anything is booked.",
            "parameters": {
                "type": "object",
                "properties": {"fare_id": {"type": "string"}},
                "required": ["fare_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trip_status",
            "description": "Get current status of a trip in this session.",
            "parameters": {
                "type": "object",
                "properties": {"trip_id": {"type": "string"}},
                "required": ["trip_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_session_trips",
            "description": "List this session's trips with ids and statuses.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_ride",
            "description": "Propose cancelling a trip. Requires the user to confirm in the UI before anything is cancelled.",
            "parameters": {
                "type": "object",
                "properties": {"trip_id": {"type": "string"}},
                "required": ["trip_id"],
            },
        },
    },
]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchPlacesArgs(_Args):
    query: str


class GetQuotesArgs(_Args):
    pickup_place_id: str
    dropoff_place_id: str


class BookRideArgs(_Args):
    fare_id: str


class GetTripStatusArgs(_Args):
    trip_id: str


class ListSessionTripsArgs(_Args):
    pass


class CancelRideArgs(_Args):
    trip_id: str


ARG_MODELS = {
    "search_places": SearchPlacesArgs,
    "get_quotes": GetQuotesArgs,
    "book_ride": BookRideArgs,
    "get_trip_status": GetTripStatusArgs,
    "list_session_trips": ListSessionTripsArgs,
    "cancel_ride": CancelRideArgs,
}
