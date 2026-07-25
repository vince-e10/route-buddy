import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone

from app.config import Settings


_PHONE = re.compile(r"\+\d{7,15}|\b[689]\d{7}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)


class RedactionFilter(logging.Filter):
    def __init__(self, secret_values: list[str]) -> None:
        super().__init__()
        self.secret_values = [value for value in secret_values if value]

    def redact(self, value: str) -> str:
        for secret in self.secret_values:
            value = value.replace(secret, "[REDACTED]")
        return _EMAIL.sub("[REDACTED]", _PHONE.sub("[REDACTED]", value))

    def redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            return {key: self.redact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        for name, value in record.__dict__.items():
            if name not in _RECORD_FIELDS:
                record.__dict__[name] = self.redact_value(value)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {
                name: value
                for name, value in record.__dict__.items()
                if name not in _RECORD_FIELDS
            }
        )
        return json.dumps(payload, default=str)


def configure_logging(current_settings: Settings | None = None) -> None:
    filter_ = RedactionFilter((current_settings or Settings.from_env()).secret_values)
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(filter_)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
