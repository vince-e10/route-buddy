import logging
import time

import httpx

from app.config import Settings, settings
from app.models import LatLng, Place


logger = logging.getLogger(__name__)


class GeocodeError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class OneMapGeocoder:
    def __init__(self, config: Settings = settings) -> None:
        self._email = config.onemap_email
        self._password = config.onemap_password
        self._client = httpx.AsyncClient(base_url=config.onemap_base_url.rstrip("/"), timeout=10.0)
        self._token: str | None = None
        self._token_expiry = 0

    async def _get_token(self) -> str:
        if self._token and time.time() <= self._token_expiry - 3600:
            return self._token
        try:
            response = await self._client.post(
                "/api/auth/post/getToken",
                json={"email": self._email, "password": self._password},
            )
            if not response.is_success:
                raise GeocodeError("Geocoding service is unavailable.")
            body = response.json()
            self._token = body["access_token"]
            self._token_expiry = int(body["expiry_timestamp"])
            return self._token
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise GeocodeError("Geocoding service is unavailable.") from None

    async def search(self, query: str) -> list[Place]:
        token = await self._get_token()
        for attempt in range(2):
            try:
                response = await self._client.get(
                    "/api/common/elastic/search",
                    params={
                        "searchVal": query,
                        "returnGeom": "Y",
                        "getAddrDetails": "Y",
                        "pageNum": 1,
                    },
                    headers={"Authorization": token},
                )
            except httpx.HTTPError:
                raise GeocodeError("Geocoding service is unavailable.") from None
            if response.status_code == 401 and attempt == 0:
                self._token = None
                self._token_expiry = 0
                token = await self._get_token()
                continue
            if not response.is_success:
                raise GeocodeError("Geocoding service is unavailable.")
            try:
                body = response.json()
            except ValueError:
                raise GeocodeError("Geocoding service is unavailable.") from None
            if body.get("found") == 0:
                return []
            return self._places(body.get("results", [])[:10])
        raise GeocodeError("Geocoding service is unavailable.")

    @staticmethod
    def _places(results: list[dict]) -> list[Place]:
        places = []
        for result in results:
            try:
                location = LatLng(lat=float(result["LATITUDE"]), lng=float(result["LONGITUDE"]))
            except (TypeError, ValueError):
                logger.warning("Skipping OneMap result with invalid coordinates: %s", result.get("SEARCHVAL"))
                continue
            postal = result.get("POSTAL")
            places.append(
                Place(
                    place_id="",
                    name=result["SEARCHVAL"],
                    address=result["ADDRESS"],
                    postal=None if postal in {"NIL", "", None} else postal,
                    location=location,
                )
            )
        return places
