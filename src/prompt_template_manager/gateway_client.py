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


class GatewayError(Exception):
    """Base class for every error `submit_and_wait` raises on purpose. The
    CLI catches this one type, so no gateway failure mode reaches the user
    as a raw httpx/json traceback."""


class GatewaySubmissionError(GatewayError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"submission rejected ({status_code}): {message}")


class GatewayJobFailedError(GatewayError):
    pass


class GatewayJobTimeoutError(GatewayError):
    pass


class GatewayConnectionError(GatewayError):
    """The gateway could not be reached (refused, DNS, TLS, network timeout)."""


class GatewayResponseError(GatewayError):
    """The gateway answered, but not with the documented submit/poll shape:
    an unexpected HTTP error while polling, a non-JSON body, or JSON that is
    missing the fields the contract promises."""


def _json_or_raise(response: httpx.Response, stage: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        snippet = response.text[:200]
        raise GatewayResponseError(
            f"{stage} response ({response.status_code}) is not JSON: {snippet!r}"
        ) from exc


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
        body_json = _json_or_raise(response, "submission") if response.status_code < 400 else None
        if body_json is not None and not isinstance(body_json, dict):
            raise GatewayResponseError(f"submission response is not a JSON object: {body_json!r}")
        try:
            job_id, polling_url = parse_submission(response.status_code, body_json, response.text)
        except GatewayHTTPError as exc:
            raise GatewaySubmissionError(exc.status_code, exc.body_text) from exc
        except KeyError as exc:
            raise GatewayResponseError(
                f"submission response is missing {exc.args[0]!r}: {body_json!r}"
            ) from exc
        del job_id  # this client's public contract only ever returns the result, not the id

        deadline = time.monotonic() + timeout
        while True:
            poll_response = client.get(resolve_polling_url(base_url, polling_url))
            if is_expired_poll_response(poll_response.status_code):
                try:
                    detail_body = poll_response.json()
                except ValueError:
                    detail_body = None
                raise GatewayJobFailedError(
                    expired_detail(detail_body if isinstance(detail_body, dict) else None)
                )
            if poll_response.status_code >= 400:
                raise GatewayResponseError(
                    f"poll of {polling_url} returned {poll_response.status_code}: {poll_response.text[:200]!r}"
                )
            poll_body = _json_or_raise(poll_response, "poll")
            if not isinstance(poll_body, dict):
                raise GatewayResponseError(f"poll response is not a JSON object: {poll_body!r}")
            outcome = classify_poll_body(poll_body)
            if outcome.ready:
                return outcome.result
            if outcome.terminal:
                raise GatewayJobFailedError(outcome.error_message)
            if time.monotonic() >= deadline:
                raise GatewayJobTimeoutError(
                    f"job did not finish within {timeout}s (last observed status: {outcome.status!r})"
                )
            time.sleep(poll_interval)
    except httpx.TransportError as exc:
        raise GatewayConnectionError(f"could not reach gateway at {base_url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
