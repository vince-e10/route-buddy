from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Session, Trip


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchPlacesArgs(_Args):
    query: str


class GetQuotesArgs(_Args):
    pickup_place_id: str
    dropoff_place_id: str


class GetTripStatusArgs(_Args):
    trip_id: str


class ListSessionTripsArgs(_Args):
    pass


ARG_MODELS = {
    "search_places": SearchPlacesArgs,
    "get_quotes": GetQuotesArgs,
    "get_trip_status": GetTripStatusArgs,
    "list_session_trips": ListSessionTripsArgs,
}


TOOL_DESCRIPTIONS = {
    "search_places": "Search Singapore places (landmarks, buildings, postal codes) and return candidates with place_ids.",
    "get_quotes": "Get ride quotes between two previously searched places. Use place_ids returned by search_places.",
    "get_trip_status": "Get current status of a trip in this session.",
    "list_session_trips": "List this session's trips with ids and statuses.",
}


def _without_titles(value):
    if isinstance(value, dict):
        return {
            key: _without_titles(child)
            for key, child in value.items()
            if key != "title"
        }
    if isinstance(value, list):
        return [_without_titles(child) for child in value]
    return value


def tool_schemas(
    names: list[str] | None = None,
    enum_values: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict]:
    selected = set(names) if names is not None else None
    schemas = []
    for name, description in TOOL_DESCRIPTIONS.items():
        if selected is not None and name not in selected:
            continue
        schema = ARG_MODELS[name].model_json_schema()
        properties = _without_titles(schema.get("properties", {}))
        for field, values in (enum_values or {}).get(name, {}).items():
            if field.endswith("_id") and field in properties:
                properties[field]["enum"] = values
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": schema.get("required", []),
                        "additionalProperties": schema.get("additionalProperties", False),
                    },
                },
            }
        )
    return schemas


def session_tool_schemas(
    session: Session, trips: list[Trip], now: datetime | None = None
) -> list[dict]:
    owned_trips = [trip for trip in trips if trip.session_id == session.session_id]
    enum_values: dict[str, dict[str, list[str]]] = {}
    names = {
        "search_places",
        "get_quotes",
        "get_trip_status",
        "list_session_trips",
    }
    place_ids = list(session.places)
    if place_ids:
        enum_values["get_quotes"] = {
            "pickup_place_id": place_ids,
            "dropoff_place_id": place_ids,
        }
    if owned_trips:
        enum_values["get_trip_status"] = {
            "trip_id": [trip.trip_id for trip in owned_trips]
        }
    return tool_schemas(list(names), enum_values)


TOOL_SCHEMAS = tool_schemas()
