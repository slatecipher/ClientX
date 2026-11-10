"""Structured logging for endpoint calls.

ClientX logs one DEBUG record per endpoint call on the ``clientx`` logger, after
the response arrives or the request fails. The record has a readable message and
a fixed set of ``clientx_*`` attributes for structured (for example JSON) log
handlers. It never contains values: no header values, bodies, or query strings.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("clientx")


@dataclass(frozen=True, slots=True)
class EndpointCall:
    """What gets logged about one endpoint call, apart from its outcome.

    Attributes:
        endpoint: Qualified name of the endpoint method, such as ``"UsersClient.get_user"``.
        method: HTTP method name, such as ``"GET"``.
        path: Rendered request path, without a query string.
        parts: Names of the request parts sent, such as ``"json"`` or ``"headers"``.
        stream: Whether the response is streamed. For a stream, the elapsed time
            covers the response headers only.
    """

    endpoint: str
    method: str
    path: str
    parts: tuple[str, ...]
    stream: bool


def log_endpoint_call(
    call: EndpointCall,
    *,
    started: float,
    status: int | None = None,
    error: BaseException | None = None,
) -> None:
    """Log one finished endpoint call at DEBUG level.

    Args:
        call: The endpoint call to log.
        started: ``time.perf_counter()`` value taken just before sending.
        status: Response status code, or ``None`` if no response arrived.
        error: The exception the call raised, or ``None`` if it succeeded. With a
            status too, the response arrived but was rejected, such as a 404
            raising ``HTTPStatusError``.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    error_name = None if error is None else type(error).__name__
    outcome = " ".join(str(part) for part in (status, error_name) if part is not None)
    logger.debug(
        "ClientX request: %s %s -> %s in %.1f ms (%s)",
        call.method,
        call.path,
        outcome,
        elapsed_ms,
        call.endpoint,
        extra={
            "clientx_endpoint": call.endpoint,
            "clientx_method": call.method,
            "clientx_path": call.path,
            "clientx_parts": sorted(call.parts),
            "clientx_stream": call.stream,
            "clientx_status": status,
            "clientx_elapsed_ms": elapsed_ms,
            "clientx_error": error_name,
        },
    )
