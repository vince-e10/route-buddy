import shutil
import subprocess
import textwrap

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_index_served_with_required_csp_and_session_storage() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' "
        "'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data:"
    ) in response.text
    assert "localStorage" in response.text


def test_static_page_has_no_innerhtml() -> None:
    response = TestClient(app).get("/")

    assert "innerHTML" not in response.text


def test_quote_and_trip_cards_send_exact_ids_from_button_closures() -> None:
    response = TestClient(app).get("/")

    assert 'select.addEventListener("click", () => requestAction("book", quote.fare_id));' in response.text
    assert 'select.addEventListener("click", () => requestAction("cancel", message.trip_id));' in response.text
    assert 'aria-label", `Select ${quote.product_name ?? "ride"}' in response.text
    assert 'aria-label", "Select trip cancellation"' in response.text
    assert "card.append(element(\"span\", quote.fare_id" not in response.text


def test_selection_locks_synchronously_and_recovers_only_usable_quotes() -> None:
    response = TestClient(app).get("/")

    assert "selectionPending = { action, targetId, token: null };" in response.text
    assert "setSelectionButtonsDisabled(true);" in response.text
    assert 'socket.send(JSON.stringify({ type: "action_request", action, target_id: targetId }));' in response.text
    assert "quote.expires_at" in response.text
    assert "const confirmationLocks = new Set();" in response.text
    assert "confirmationLocks.add(message.token);" in response.text
    assert "confirmationMatchesSelection(action, message.summary || {})" in response.text
    assert "summary.trip_id === selectionPending.targetId" in response.text
    assert "item.fareId === selectionPending.targetId" in response.text
    assert "choice.productName === summary.product_name" in response.text
    assert "choice.priceDisplay === summary.price_display" in response.text
    assert "selectionPending.token = message.token;" in response.text
    assert "Boolean(selectionPending) || confirmationLocks.size > 0" in response.text
    assert "if (selectionPending?.token === token) selectionPending = null;" in response.text
    assert "confirmationLocks.delete(token);" in response.text
    assert "if (selectionPending && !selectionPending.token) selectionPending = null;" in response.text
    assert "resolveConfirmation(message.token, message.result, true);\n        clearSelectionPending();" not in response.text


def test_session_storage_value_is_validated_as_uuid_v4() -> None:
    response = TestClient(app).get("/")

    assert "const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;" in response.text
    assert "if (!UUID_V4.test(sessionId || \"\"))" in response.text
    assert "sessionId = crypto.randomUUID();" in response.text


def test_websocket_confirmation_resolution_outweighs_late_http_or_transport_results() -> None:
    response = TestClient(app).get("/")

    assert "function isConfirmationResult(result)" in response.text
    assert "if (!response.ok || !isConfirmationResult(result))" in response.text
    assert "if (confirmation.websocketResolved && !authoritative) return;" in response.text
    assert "resolveConfirmation(message.token, message.result, true);" in response.text
    assert "if (confirmation && !confirmation.websocketResolved)" in response.text
    assert 'resolveConfirmation(message.token, "failed");' not in response.text


def test_confirmation_locks_correlate_exact_selections_at_runtime(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    html = TestClient(app).get("/").text
    script = html.partition("<script>")[2].partition("</script>")[0]
    harness = textwrap.dedent(
        """
        class FakeElement {
          constructor() {
            this.children = [];
            this.classList = { add() {}, toggle() {} };
            this.listeners = {};
            this.disabled = false;
            this.textContent = "";
            this.value = "";
          }
          append(...nodes) { this.children.push(...nodes); }
          addEventListener(name, callback) { this.listeners[name] = callback; }
          replaceChildren(...nodes) { this.children = nodes; }
          scrollIntoView() {}
          setAttribute() {}
        }
        const roots = new Map();
        const document = {
          createElement() { return new FakeElement(); },
          getElementById(id) {
            if (!roots.has(id)) roots.set(id, new FakeElement());
            return roots.get(id);
          },
        };
        const localStorage = {
          value: null,
          getItem() { return this.value; },
          setItem(key, value) { this.value = value; },
        };
        const crypto = { randomUUID() { return "00000000-0000-4000-8000-000000000001"; } };
        const location = { protocol: "http:", host: "localhost" };
        const window = { setTimeout() {} };
        function setInterval() { return 1; }
        function clearInterval() {}
        function fetch() { throw new Error("fetch should not run"); }
        class FakeWebSocket {
          static OPEN = 1;
          constructor() {
            this.readyState = FakeWebSocket.OPEN;
            this.listeners = {};
            this.sent = [];
            FakeWebSocket.last = this;
          }
          addEventListener(name, callback) { this.listeners[name] = callback; }
          send(value) { this.sent.push(JSON.parse(value)); }
          emit(name) { this.listeners[name]?.({}); }
        }
        const WebSocket = FakeWebSocket;
        """
    )
    assertions = textwrap.dedent(
        """
        const future = "2099-01-01T00:00:00Z";
        renderQuotes({ items: [
          { fare_id: "fare-a", product_name: "A", price_display: "SGD 10", expires_at: future },
          { fare_id: "fare-b", product_name: "B", price_display: "SGD 20", expires_at: future },
        ] });
        requestAction("book", "fare-a");
        renderConfirmationRequest({
          token: "own-book",
          action: "book",
          summary: { product_name: "A", price_display: "SGD 10", expires_at: future },
        });
        renderConfirmationRequest({
          token: "other-book",
          action: "book",
          summary: { product_name: "B", price_display: "SGD 20", expires_at: future },
        });
        if (selectionPending?.token !== "own-book") throw new Error("wrong booking token");
        renderConfirmationResolved({ token: "other-book", result: "dismissed" });
        if (!selectionPending || !selectionLocked()) throw new Error("unrelated resolution unlocked selection");
        renderQuotes({ items: [
          { fare_id: "fare-c", product_name: "C", price_display: "SGD 30", expires_at: future },
        ] });
        if (!quoteChoices.at(-1).button.disabled) throw new Error("new quote rendered unlocked");
        renderConfirmationResolved({ token: "own-book", result: "dismissed" });
        if (selectionPending || selectionLocked()) throw new Error("matching resolution stayed locked");

        renderTripUpdate({
          trip_id: "trip-a",
          status: "accepted",
          product_name: "A",
          price_display: "SGD 10",
        });
        requestAction("cancel", "trip-a");
        renderConfirmationRequest({
          token: "other-cancel",
          action: "cancel",
          summary: { trip_id: "trip-b", expires_at: future },
        });
        if (selectionPending?.token) throw new Error("wrong cancellation token");
        FakeWebSocket.last.emit("close");
        if (selectionPending) throw new Error("undisclosed selection did not recover");
        if (!confirmationLocks.has("other-cancel")) throw new Error("disclosed token was lost");
        renderConfirmationResolved({ token: "other-cancel", result: "dismissed" });
        if (selectionLocked()) throw new Error("resolved token stayed locked");
        """
    )
    path = tmp_path / "confirmation-lock-runtime.mjs"
    path.write_text(harness + script + assertions)

    result = subprocess.run(
        [node, "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [node, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
