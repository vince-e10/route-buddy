import logging

from app.logging_setup import configure_logging


def log_message(capsys, message: str, extra: dict | None = None) -> str:
    configure_logging()
    logging.getLogger("route_buddy.child").warning(message, extra=extra)
    return capsys.readouterr().out


def test_redacts_phone(capsys) -> None:
    output = log_message(capsys, "call +6591234567 now")

    assert "[REDACTED]" in output
    assert "+6591234567" not in output


def test_redacts_sg_local_phone(capsys) -> None:
    output = log_message(capsys, "call 91234567")

    assert "[REDACTED]" in output
    assert "91234567" not in output


def test_redacts_email(capsys) -> None:
    output = log_message(capsys, "mail a.b+c@example.com")

    assert "[REDACTED]" in output
    assert "a.b+c@example.com" not in output


def test_redacts_secret_value(capsys, monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", "supersecret123")

    output = log_message(capsys, "secret supersecret123")

    assert "[REDACTED]" in output
    assert "supersecret123" not in output


def test_normal_text_untouched(capsys) -> None:
    output = log_message(capsys, "quote SGD 15.50 for UberX")

    assert "quote SGD 15.50 for UberX" in output


def test_redacts_sensitive_child_logger_extra_values(capsys, monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", "supersecret123")

    output = log_message(
        capsys,
        "provider request",
        {"rider": {"phone": "+6591234567", "token": "supersecret123"}},
    )

    assert "[REDACTED]" in output
    assert "+6591234567" not in output
    assert "supersecret123" not in output
