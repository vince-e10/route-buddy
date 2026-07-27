from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.config import Settings
from app.storage._dynamo import _from_ddb, _to_ddb


def test_dynamodb_serializers_preserve_nested_values() -> None:
    value = {
        "items": [1, 1.5, {"nested": 2.25}],
        "timestamp": datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc).isoformat(),
    }

    stored = _to_ddb(value)

    assert stored == {
        "items": [1, Decimal("1.5"), {"nested": Decimal("2.25")}],
        "timestamp": "2026-07-26T12:00:00+00:00",
    }
    assert _from_ddb(stored) == value


def test_table_name_settings_default_and_allow_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = {
        "SESSIONS_TABLE": "demo-sessions",
        "TRIPS_TABLE": "demo-trips",
        "ACTION_LOG_TABLE": "demo-action-log",
        "PENDING_ACTIONS_TABLE": "demo-pending-actions",
    }
    for name in names:
        monkeypatch.delenv(name, raising=False)

    defaults = Settings.from_env()

    assert (
        defaults.sessions_table,
        defaults.trips_table,
        defaults.action_log_table,
        defaults.pending_actions_table,
    ) == ("sessions", "trips", "action_log", "pending_actions")

    for name, value in names.items():
        monkeypatch.setenv(name, value)

    overridden = Settings.from_env()

    assert (
        overridden.sessions_table,
        overridden.trips_table,
        overridden.action_log_table,
        overridden.pending_actions_table,
    ) == (
        "demo-sessions",
        "demo-trips",
        "demo-action-log",
        "demo-pending-actions",
    )
