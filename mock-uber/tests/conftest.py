import pytest
from starlette.testclient import TestClient

from app.main import app
from app.sim import Simulator
from app.store import Store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOCK_DETERMINISTIC", "1")
    app.state.store = Store()
    app.state.simulator = Simulator(app.state.store)

    async def webhook_success(_payload):
        return True

    monkeypatch.setattr(app.state.simulator, "_post_webhook", webhook_success)
    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(app.state.store.cancel_and_drain_tasks)


@pytest.fixture
def auth_headers():
    return {
        "authorization": "Bearer test-token",
        "x-uber-organizationuuid": "test-org",
    }
