"""Fixtures shared by the test modules.

pytest finds this file by itself and passes a fixture to every test that names it
as a parameter. The suite runs in pytest's recommended ``importlib`` import mode,
where test modules can't import each other or a helper module, so shared helpers
are fixtures. Each one returns a function, so a test can call it as often as it
needs, with different arguments ("factories as fixtures").
"""

from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from clientx._endpoint_context import Endpoint
from clientx._registry import endpoint_for

type Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture
def endpoint_of() -> Callable[[object], Endpoint]:
    """Return a function that gives the ``Endpoint`` behind a decorated method, failing the test if there isn't one."""

    def find(function: object) -> Endpoint:
        endpoint = endpoint_for(function)
        assert endpoint is not None
        return endpoint

    return find


@pytest.fixture
def mock_transport() -> Callable[..., httpx2.MockTransport]:
    """Return a function that builds a transport answering every request without a network.

    It's called as ``mock_transport(sent=None, handler=None, *, status=200, **response)``.
    Each request is appended to ``sent``, if given. The answer comes from ``handler`` if
    given, or else is a new ``httpx2.Response(status, **response)`` for each request, such
    as ``mock_transport(sent, json={"id": 1})`` or ``mock_transport(status=404)``.
    """

    def build(
        sent: list[httpx2.Request] | None = None,
        handler: Handler | None = None,
        *,
        status: int = 200,
        **response: Any,
    ) -> httpx2.MockTransport:
        def answer(request: httpx2.Request) -> httpx2.Response:
            if sent is not None:
                sent.append(request)
            if handler is not None:
                return handler(request)
            return httpx2.Response(status, **response)

        return httpx2.MockTransport(answer)

    return build
