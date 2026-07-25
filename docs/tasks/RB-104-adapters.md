# RB-104: Adapters - UberAdapter (RideProvider) and OneMapGeocoder (Geocoder)

| Field | Value |
|---|---|
| Type | Task |
| Wave | 2 (parallel with RB-102, RB-103) |
| Depends on | RB-101 |
| Blocks | RB-105, RB-107 |
| Size | M |

## Context

These two classes are the system's swappable seams to the outside world (design.md section 7).
`UberAdapter` implements the `RideProvider` protocol against the Guest Rides HTTP contract - the
SAME contract whether it points at mock-uber (local) or real Uber (prod); the base URL and
credentials are env config. `OneMapGeocoder` implements `Geocoder` against Singapore's OneMap
search API and owns the full token lifecycle (login, cache, refresh) internally so nothing else in
the system knows OneMap has tokens.

You own `api/app/providers/uber.py`, `api/app/geocode/{onemap,stub}.py`, and
`api/tests/{providers,geocode}/**` only (CONTRACTS section 13). RB-102 (mock-uber) is being built
in parallel - do NOT call it in your tests; test against `respx`-mocked responses copied verbatim
from CONTRACTS section 9 (same source of truth RB-102 implements; RB-107 proves the live pairing).

## Required reading

1. `docs/CONTRACTS.md` sections 2 (env), 5 (protocols - implement exactly), 9 (Guest Rides
   contract - your request/response shapes), 11 (OneMap contract, live-verified)
2. `docs/design.md` sections 3.4 (OneMap research), 6.4, 7

## Scope

### 1. `api/app/providers/uber.py` - `UberAdapter`

Constructor reads from `Settings`: `UBER_BASE_URL`, `UBER_API_TOKEN`, `UBER_ORG_UUID`. One shared
`httpx.AsyncClient` (timeout 10s). Every request sends headers
`authorization: Bearer {UBER_API_TOKEN}`, `x-uber-organizationuuid: {UBER_ORG_UUID}`,
`content-type: application/json`.

- `get_quotes(pickup, dropoff, pickup_label, dropoff_label) -> list[Quote]`:
  `POST {base}/v1/guests/trips/estimates` with
  `{"pickup": {"latitude": pickup.lat, "longitude": pickup.lng}, "dropoff": {...}}`.
  Map each `product_estimates[]` element to a `Quote`:
  `fare_id <- estimate_info.fare_id`, `product_id <- product.product_id`,
  `product_name <- product.display_name`, `capacity <- product.capacity`,
  `price_value <- estimate_info.fare.value`, `price_display <- estimate_info.fare.display`,
  `currency <- estimate_info.fare.currency_code`,
  `pickup_eta_minutes <- estimate_info.pickup_estimate`,
  `duration_minutes <- round(estimate_info.trip.duration_estimate / 60)`,
  `distance_km <- estimate_info.trip.distance_estimate`,
  `surge_multiplier <- 1.0` (mock carries surge inside the fare; field kept for real-API parity),
  `expires_at <- utc datetime from epoch estimate_info.fare.expires_at`,
  `pickup/dropoff/pickup_label/dropoff_label <- arguments`.
- `book(quote, guest) -> ProviderTripState`: `POST {base}/v1/guests/trips` with
  `{"guest": {"first_name": ..., "last_name": ..., "phone_number": ...},
  "product_id": quote.product_id, "fare_id": quote.fare_id,
  "pickup": {"latitude": quote.pickup.lat, "longitude": quote.pickup.lng}, "dropoff": {...}}`.
  Map to `ProviderTripState(provider_request_id=request_id, status=TripStatus(status), driver=None)`.
- `get_trip(provider_request_id)`: `GET {base}/v1/guests/trips/{id}` -> `ProviderTripState`
  (driver mapped when present).
- `cancel(provider_request_id)`: `DELETE {base}/v1/guests/trips/{id}` -> `ProviderTripState`.
- **Error policy** (uniform): raise `ProviderError(code: str, status_code: int, detail: str)`
  (define it in this module) for any non-2xx, mapping the body's `code` field when present
  (`fare_expired`, `not_cancellable`, `invalid_guest`, `invalid_product`, `not_found`,
  `unauthorized`) and `code="provider_unreachable"` for transport errors/timeouts. Callers
  (RB-105) branch on `.code`. Never retry writes (a booking POST is not idempotent); read
  endpoints may retry once on transport error.

### 2. `api/app/geocode/onemap.py` - `OneMapGeocoder`

Constructor reads `ONEMAP_BASE_URL`, `ONEMAP_EMAIL`, `ONEMAP_PASSWORD`. Internal token state:
`_token: str | None`, `_token_expiry: int` (epoch).

- `_get_token()`: if `_token` is None or `now > _token_expiry - 3600` (refresh within 1h of
  expiry): `POST {base}/api/auth/post/getToken` json `{"email", "password"}`; store
  `access_token` and `int(expiry_timestamp)`. The token value must NEVER be logged (it is
  covered by no redaction regex - just do not log it).
- `search(query) -> list[Place]`:
  `GET {base}/api/common/elastic/search?searchVal={query}&returnGeom=Y&getAddrDetails=Y&pageNum=1`
  with header `Authorization: {token}`. On 401: refresh token once, retry once, then raise
  `GeocodeError(detail)` (define in module). Parse `results[]` (first page only, max 10):
  `Place(place_id="", name=SEARCHVAL, address=ADDRESS,
  postal=(None if POSTAL in ("NIL", "", None) else POSTAL),
  location=LatLng(lat=float(LATITUDE), lng=float(LONGITUDE)))`.
  ALL OneMap values are strings; a float parse failure = SKIP that result and log a warning with
  the SEARCHVAL only - never guess coordinates (grounding invariant). `found == 0` -> `[]`.
  `place_id` is left empty; the tool layer (RB-105) assigns ids when caching into the session.

### 3. `api/app/geocode/stub.py` - `StubGeocoder`

Implements `Geocoder`. Constructor takes `dict[str, list[Place]]` (query substring -> places,
case-insensitive matching); `search` returns the first matching entry else `[]`. Used by RB-105
tests and fake-LLM e2e mode. Provide module-level `DEMO_PLACES` with two entries usable by later
tickets: "changi airport" -> Place(name="CHANGI AIRPORT TERMINAL 3", address="65 AIRPORT
BOULEVARD ...", postal="819663", lat 1.35735, lng 103.98803) and "marina bay sands" ->
Place(name="MARINA BAY SANDS", address="1 BAYFRONT AVENUE ...", postal="018971", lat 1.28345,
lng 103.86081).

## Out of scope

Lyft/Grab adapters, plugin registry, OAuth client-credentials flow (static bearer for MVP - real
flow lands with the real-Uber swap), reverse geocoding, calling live OneMap or mock-uber in tests.

## Interfaces produced

- `UberAdapter()` and `OneMapGeocoder()` satisfying CONTRACTS section 5 protocols, plus
  `ProviderError` and `GeocodeError` exception types (RB-105 catches them)
- `StubGeocoder` + `DEMO_PLACES` for downstream tests

## Test plan (pytest + respx; NO live network, NO mock-uber dependency)

`tests/providers/test_uber_adapter.py`:
- `test_get_quotes_mapping` - respx-mock the estimates endpoint with the VERBATIM sample body
  from CONTRACTS section 9; assert one `Quote` per product with every field mapped per the table
  above (spot-assert fare_id, price_value 15.5, price_display "SGD 15.50", duration_minutes 18,
  expires_at is a datetime)
- `test_headers_sent` - respx asserts `authorization`, `x-uber-organizationuuid` present on the
  request
- `test_book_mapping` - mock create-trip response; assert request body shape (guest fields,
  product_id, fare_id) and returned `ProviderTripState(status=processing)`
- `test_fare_expired_maps_to_provider_error` - 410 `{"code":"fare_expired"}` raises
  `ProviderError(code="fare_expired", status_code=410)`
- `test_not_cancellable` - DELETE 409 -> `ProviderError(code="not_cancellable")`
- `test_transport_error` - respx side_effect `httpx.ConnectError` -> `code="provider_unreachable"`
- `test_no_retry_on_book` - book endpoint fails once with ConnectError; assert exactly ONE request
  was made (writes never retry)

`tests/geocode/test_onemap.py`:
- `test_token_fetched_once_then_cached` - two searches, respx counts exactly one getToken call
- `test_token_refresh_near_expiry` - force `_token_expiry = now + 100`, next search re-fetches
- `test_search_parses_fields` - mock the VERBATIM Marina Bay Sands response from design.md 3.4;
  assert Place fields incl. float coords, postal string
- `test_postal_nil_becomes_none`
- `test_unparseable_latitude_skipped` - one result with `LATITUDE: "abc"` -> that result absent,
  others returned
- `test_401_refreshes_and_retries_once` - first search response 401, then success after re-token
- `test_zero_found_returns_empty`

`tests/geocode/test_stub.py`:
- `test_demo_places_lookup` - "take me to Changi Airport please" query "changi airport" returns
  the demo place; unknown query -> `[]`

## Security checklist

- [ ] OneMap token and password never appear in any log statement or exception message
- [ ] `UBER_API_TOKEN` never logged
- [ ] Guest PII appears only in the book request body, never in logs from this module

## Acceptance criteria

- [ ] All tests pass: `cd api && python -m pytest tests/providers tests/geocode -v` (host or
      in-container; no other services needed)
- [ ] Both classes satisfy the protocols (mypy-style structural check or a small
      `isinstance`-free assertion test that assigns them to protocol-typed variables)
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters
- [ ] Only owned files created/modified (CONTRACTS section 13)

## Definition of done

All boxes checked; close-out note at the bottom of this file: what was built, deviations (owner
approval first), exact verify commands.
