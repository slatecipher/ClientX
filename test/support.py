"""Helpers shared by the test modules.

pytest puts this directory on ``sys.path``, so a test module imports them with
``from support import ...``. The file isn't collected: its name doesn't start with ``test_``.
"""

from collections.abc import Callable
from typing import Any

import httpx2

from clientx._endpoint_context import Endpoint
from clientx._registry import endpoint_for

type Handler = Callable[[httpx2.Request], httpx2.Response]


def endpoint_of(function: object) -> Endpoint:
    """Return the ``Endpoint`` behind a decorated endpoint method, failing the test if there isn't one."""
    endpoint = endpoint_for(function)
    assert endpoint is not None
    return endpoint


def mock_transport(
    sent: list[httpx2.Request] | None = None,
    handler: Handler | None = None,
    *,
    status: int = 200,
    **response: Any,
) -> httpx2.MockTransport:
    """Return a transport that answers every request without a network.

    Each request is appended to ``sent``, if given. The answer comes from ``handler``
    if given, or else is a new ``httpx2.Response(status, **response)`` for each request,
    such as ``mock_transport(sent, json={"id": 1})`` or ``mock_transport(status=404)``.
    """

    def answer(request: httpx2.Request) -> httpx2.Response:
        if sent is not None:
            sent.append(request)
        if handler is not None:
            return handler(request)
        return httpx2.Response(status, **response)

    return httpx2.MockTransport(answer)
