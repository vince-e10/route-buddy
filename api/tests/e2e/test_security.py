import json
import os
from pathlib import Path

import httpx
from app.config import SECRET_ENV_VARS


API_URL = "http://api:8000"
EVIDENCE_DIR = Path("/tmp/route-buddy-e2e")


def _evidence(name: str) -> str:
    return (EVIDENCE_DIR / name).read_text()


def test_safe_compose_evidence_excludes_runtime_secrets():
    config = _evidence("docker-compose.yml")
    for name in SECRET_ENV_VARS:
        value = os.getenv(name, "")
        if value:
            assert value not in config


def test_api_and_mock_uber_run_as_nonroot():
    assert int(_evidence("api-uid.txt")) > 0
    assert int(_evidence("mock-uber-uid.txt")) > 0


def test_only_api_has_a_published_host_port():
    services = json.loads(_evidence("compose-ps.jsonl"))
    published = {
        service["Service"]
        for service in services
        if any(publisher.get("PublishedPort") for publisher in service.get("Publishers") or [])
    }
    assert published == {"api"}


def test_bad_webhook_secret_is_unauthorized():
    payload = {
        "event_id": "evt_bad_secret",
        "event_time": 1,
        "event_type": "guests.trips.status_changed",
        "resource_href": "http://mock-uber:8001/v1/guests/trips/missing",
        "meta": {
            "user_id": "mock-user",
            "org_uuid": "mock-org-uuid",
            "resource_id": "missing",
            "status": "accepted",
        },
    }
    response = httpx.post(
        f"{API_URL}/webhooks/uber",
        json=payload,
        headers={"X-Webhook-Secret": "wrong"},
        timeout=5,
    )
    assert response.status_code == 401


def test_health_has_nosniff_header():
    response = httpx.get(f"{API_URL}/healthz", timeout=5)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
