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
        response = client.post(f"{base_url}/v1/{capability}", json=params)
        if response.status_code >= 400:
            raise GatewaySubmissionError(response.status_code, response.text)
        polling_url = response.json()["polling_url"]

        deadline = time.monotonic() + timeout
        while True:
            poll_response = client.get(base_url + polling_url)
            poll_response.raise_for_status()
            record = poll_response.json()
            status = record["status"]
            if status == "ready":
                return record["result"]
            if status == "error":
                raise GatewayJobFailedError(record.get("error") or "job failed with no error message")
            if status == "expired":
                raise GatewayJobFailedError(record.get("error") or "job result expired")
            if time.monotonic() >= deadline:
                raise GatewayJobTimeoutError(
                    f"job did not finish within {timeout}s (last observed status: {status!r})"
                )
            time.sleep(poll_interval)
    finally:
        if owns_client:
            client.close()
