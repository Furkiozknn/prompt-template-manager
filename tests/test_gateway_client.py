from __future__ import annotations

import json

import httpx
import pytest

from prompt_template_manager.gateway_client import (
    GatewayConnectionError,
    GatewayError,
    GatewayJobFailedError,
    GatewayJobTimeoutError,
    GatewayResponseError,
    GatewaySubmissionError,
    submit_and_wait,
)


def _client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_submit_and_wait_happy_path():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(200, json={"status": "ready", "result": {"ok": True}})

    result = submit_and_wait(
        "http://gateway.test", "echo", {"a": 1}, poll_interval=0, http_client=_client_for(handler)
    )
    assert result == {"ok": True}


def test_submit_rejected_raises_gateway_submission_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text=json.dumps({"detail": "bad request"}))

    with pytest.raises(GatewaySubmissionError) as exc_info:
        submit_and_wait("http://gateway.test", "echo", {}, http_client=_client_for(handler))
    assert exc_info.value.status_code == 422


def test_job_error_status_raises_gateway_job_failed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        return httpx.Response(200, json={"status": "error", "error": "provider exploded"})

    with pytest.raises(GatewayJobFailedError, match="provider exploded"):
        submit_and_wait(
            "http://gateway.test", "echo", {"a": 1}, poll_interval=0, http_client=_client_for(handler)
        )


def test_job_expired_status_raises_gateway_job_failed_error():
    """The server returns 410 Gone (not a 200 body with status='expired')
    once a terminal job's result has passed its TTL -- this must surface as
    a clean GatewayJobFailedError, not an unhandled httpx.HTTPStatusError."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        return httpx.Response(410, json={"detail": "this job's result has expired"})

    with pytest.raises(GatewayJobFailedError, match="expired"):
        submit_and_wait(
            "http://gateway.test", "echo", {"a": 1}, poll_interval=0, http_client=_client_for(handler)
        )


def test_never_ready_times_out():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        return httpx.Response(200, json={"status": "processing"})

    with pytest.raises(GatewayJobTimeoutError):
        submit_and_wait(
            "http://gateway.test",
            "echo",
            {"a": 1},
            timeout=0.05,
            poll_interval=0.01,
            http_client=_client_for(handler),
        )


def test_base_url_trailing_slash_does_not_produce_a_double_slash():
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        return httpx.Response(200, json={"status": "ready", "result": {}})

    submit_and_wait(
        "http://gateway.test/", "echo", {"a": 1}, poll_interval=0, http_client=_client_for(handler)
    )
    assert seen_paths == ["/v1/echo", "/v1/jobs/job-1"]
    assert not any("//" in p for p in seen_paths)


def _accepting(poll_response):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job-1", "polling_url": "/v1/jobs/job-1"})
        return poll_response
    return handler


def test_unreachable_gateway_raises_gateway_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(GatewayConnectionError, match="could not reach gateway"):
        submit_and_wait("http://gateway.test", "echo", {}, http_client=_client_for(handler))


def test_poll_http_error_raises_gateway_response_error_not_httpx_error():
    handler = _accepting(httpx.Response(500, text="boom"))
    with pytest.raises(GatewayResponseError, match="500"):
        submit_and_wait("http://gateway.test", "echo", {}, poll_interval=0, http_client=_client_for(handler))


@pytest.mark.parametrize(
    "submit_response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(202, json={"unexpected": True}),
        httpx.Response(202, json=["a", "list"]),
    ],
)
def test_malformed_submission_response_raises_gateway_response_error(submit_response):
    with pytest.raises(GatewayResponseError, match="submission"):
        submit_and_wait("http://gateway.test", "echo", {}, http_client=_client_for(lambda r: submit_response))


def test_non_json_poll_body_raises_gateway_response_error():
    handler = _accepting(httpx.Response(200, text="nope"))
    with pytest.raises(GatewayResponseError, match="poll"):
        submit_and_wait("http://gateway.test", "echo", {}, poll_interval=0, http_client=_client_for(handler))


def test_expired_with_non_json_body_still_reports_expiry():
    handler = _accepting(httpx.Response(410, text="gone"))
    with pytest.raises(GatewayJobFailedError, match="expired"):
        submit_and_wait("http://gateway.test", "echo", {}, poll_interval=0, http_client=_client_for(handler))


def test_all_gateway_errors_share_a_base_class():
    for cls in (GatewaySubmissionError, GatewayJobFailedError, GatewayJobTimeoutError,
                GatewayConnectionError, GatewayResponseError):
        assert issubclass(cls, GatewayError)
