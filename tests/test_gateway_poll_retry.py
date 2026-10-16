"""submit_and_wait retries a transient poll failure a bounded number of
times instead of giving up on a job that is still running."""

from __future__ import annotations

import httpx
import pytest

from prompt_template_manager import gateway_client as gc
from prompt_template_manager.gateway_client import (
    GatewayConnectionError,
    GatewayResponseError,
    submit_and_wait,
)


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Keep the real retry count, drop the real waits."""
    count = len(gc.poll_retry_delays())
    monkeypatch.setattr(gc, "poll_retry_delays", lambda: [0.0] * count)
    return count


def _client(poll_answers):
    gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        index = gets["n"]
        gets["n"] += 1
        if index < len(poll_answers):
            item = poll_answers[index]
            if isinstance(item, Exception):
                raise item
            return item
        return httpx.Response(200, json={"status": "ready", "result": {"ok": True}})

    return httpx.Client(transport=httpx.MockTransport(handler)), gets


def test_a_dropped_connection_and_a_503_are_retried():
    client, gets = _client([httpx.ConnectError("reset"), httpx.Response(503, text="busy")])
    result = submit_and_wait("http://gw.test", "echo", {"a": 1}, poll_interval=0, http_client=client)
    assert result == {"ok": True}
    assert gets["n"] == 3


def test_retries_are_bounded_then_the_connection_error_surfaces(_fast_retries):
    client, gets = _client([httpx.ConnectError("refused")] * (_fast_retries + 1))
    with pytest.raises(GatewayConnectionError, match="could not reach gateway"):
        submit_and_wait("http://gw.test", "echo", {"a": 1}, poll_interval=0, http_client=client)
    assert gets["n"] == _fast_retries + 1


def test_a_persistent_504_is_reported_after_the_retries(_fast_retries):
    client, gets = _client([httpx.Response(504, text="timeout")] * (_fast_retries + 1))
    with pytest.raises(GatewayResponseError, match="returned 504"):
        submit_and_wait("http://gw.test", "echo", {"a": 1}, poll_interval=0, http_client=client)
    assert gets["n"] == _fast_retries + 1


@pytest.mark.parametrize("status", [500, 404])
def test_non_transient_poll_errors_are_not_retried(status):
    client, gets = _client([httpx.Response(status, text="no")])
    with pytest.raises(GatewayResponseError, match=f"returned {status}"):
        submit_and_wait("http://gw.test", "echo", {"a": 1}, poll_interval=0, http_client=client)
    assert gets["n"] == 1


def test_no_retry_waits_past_the_timeout(monkeypatch):
    monkeypatch.setattr(gc, "poll_retry_delays", lambda: [30.0])
    client, gets = _client([httpx.Response(503, text="busy")])
    with pytest.raises(GatewayResponseError, match="returned 503"):
        submit_and_wait("http://gw.test", "echo", {"a": 1}, timeout=1.0, poll_interval=0, http_client=client)
    assert gets["n"] == 1


def test_a_submission_without_polling_url_still_names_the_field():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202, json={"id": "job-1"})))
    with pytest.raises(GatewayResponseError, match="missing 'polling_url'"):
        submit_and_wait("http://gw.test", "echo", {"a": 1}, poll_interval=0, http_client=client)
