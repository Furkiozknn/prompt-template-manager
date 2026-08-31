"""Optional integration with an ai-job-gateway-compatible server.

Deliberately not a Python dependency on the `ai-job-gateway` package itself
- these are two independent repos in the same ecosystem, and the only thing
that should couple them is the documented HTTP contract (submit/poll), not
an import. Anything implementing that same submit/poll shape works here,
not just ai-job-gateway specifically.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .gateway_poll import (
    GatewayHTTPError,
    classify_poll_body,
    expired_detail,
    is_expired_poll_response,
    parse_submission,
    resolve_polling_url,
    submit_url,
)


class GatewaySubmissionError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"submission rejected ({status_code}): {message}")


class GatewayJobFailedError(Exception):
    pass


class GatewayJobTimeoutError(Exception):
    pass


def submit_and_wait(
    gateway_url: str,
    capability: str,
    params: dict[str, Any],
    *,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
    http_client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """POST params to {gateway_url}/v1/{capability}, poll until ready, return the result.

    Synchronous by design - this is a CLI convenience, not a library meant
    for embedding in an async application (use the gateway's own client for
    that).
    """
    client = http_client or httpx.Client()
    owns_client = http_client is None
    base_url = gateway_url.rstrip("/")
    try:
        response = client.post(submit_url(base_url, capability), json=params)
        body_json = response.json() if response.status_code < 400 else None
        try:
            job_id, polling_url = parse_submission(response.status_code, body_json, response.text)
        except GatewayHTTPError as exc:
            raise GatewaySubmissionError(exc.status_code, exc.body_text) from exc
        del job_id  # this client's public contract only ever returns the result, not the id

        deadline = time.monotonic() + timeout
        while True:
            poll_response = client.get(resolve_polling_url(base_url, polling_url))
            if is_expired_poll_response(poll_response.status_code):
                raise GatewayJobFailedError(expired_detail(poll_response.json()))
            poll_response.raise_for_status()
            outcome = classify_poll_body(poll_response.json())
            if outcome.ready:
                return outcome.result
            if outcome.terminal:
                raise GatewayJobFailedError(outcome.error_message)
            if time.monotonic() >= deadline:
                raise GatewayJobTimeoutError(
                    f"job did not finish within {timeout}s (last observed status: {outcome.status!r})"
                )
            time.sleep(poll_interval)
    finally:
        if owns_client:
            client.close()
