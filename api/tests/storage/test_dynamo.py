from datetime import datetime, timezone
from decimal import Decimal

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
