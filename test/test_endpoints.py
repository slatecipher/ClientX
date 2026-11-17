"""Endpoint options and rules: the HTTP method, deprecated=, timeout=, and the parameters an endpoint can have."""

import linecache
import re
import warnings
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from clientx import AsyncClientX, ClientX, DefinitionError, Timeout, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


@pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete", "head", "options"])
def test_each_verb_sends_its_http_method(verb: str, mock_transport: MockTransport) -> None:
    def call(self: ClientX) -> None: ...

    api_class: Any = type("API", (ClientX,), {"call": getattr(method, verb)("/items")(call)})
    sent: list[httpx2.Request] = []
    api_class(BASE_URL, transport=mock_transport(sent)).call()
    assert only_request(sent).method == verb.upper()


# deprecated=


def test_a_deprecated_endpoint_warns_at_the_callers_line(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/old", deprecated="Use new() instead.")
        def old(self) -> None: ...

    api = API(BASE_URL, transport=mock_transport())
    with pytest.warns(DeprecationWarning, match=re.escape("Use new() instead.")) as caught:
        api.old()  # The warning names this line.
    (warning,) = caught
    assert warning.filename == __file__
    assert linecache.getline(warning.filename, warning.lineno).strip() == "api.old()  # The warning names this line."


@pytest.mark.anyio
async def test_a_deprecated_async_endpoint_warns_at_the_callers_line(mock_transport: MockTransport) -> None:
    class API(AsyncClientX):
        @method.get("/old", deprecated="Use new() instead.")
        async def old(self) -> None: ...

    api = API(BASE_URL, transport=mock_transport())
    with pytest.warns(DeprecationWarning, match=re.escape("Use new() instead.")) as caught:
        await api.old()
    (warning,) = caught
    assert warning.filename == __file__


def test_an_endpoint_that_isnt_deprecated_doesnt_warn(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/current")
        def current(self) -> None: ...

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        API(BASE_URL, transport=mock_transport()).current()


# timeout=


def test_an_endpoints_timeout_reaches_the_transport(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/default")
        def default(self) -> None: ...

        @method.get("/slow", timeout=2.5)
        def slow(self) -> None: ...

        @method.get("/forever", timeout=None)
        def forever(self) -> None: ...

        @method.get("/split", timeout=Timeout(5.0, connect=1.0))
        def split(self) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent), timeout=10.0)
    api.default()
    api.slow()
    api.forever()
    api.split()
    assert [request.extensions["timeout"] for request in sent] == [
        {"connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0},
        {"connect": 2.5, "read": 2.5, "write": 2.5, "pool": 2.5},
        {"connect": None, "read": None, "write": None, "pool": None},
        {"connect": 1.0, "read": 5.0, "write": 5.0, "pool": 5.0},
    ]


# Parameters


def test_positional_only_and_keyword_only_parameters_work(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items/{item_id}")
        def item(self, item_id: int, /, *, verbose: bool = False) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).item(7, verbose=True)
    assert only_request(sent).url.raw_path == b"/items/7?verbose=true"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param("def call(self, *ids: int) -> None: ...", "can't take `*ids`", id="*args"),
        pytest.param("def call(self, **extra: str) -> None: ...", "can't take `**extra`", id="**kwargs"),
        pytest.param("def call() -> None: ...", "needs a positional first parameter", id="no parameters"),
        pytest.param("def call(*, self) -> None: ...", "needs a positional first parameter", id="keyword-only first"),
        pytest.param("def call(*args) -> None: ...", "needs a positional first parameter", id="*args first"),
    ],
)
def test_an_endpoints_parameters_are_checked_when_it_is_decorated(source: str, message: str) -> None:
    namespace: dict[str, object] = {}
    exec(source, namespace)  # noqa: S102 - each signature is written out as source, the clearest way to list them
    with pytest.raises(DefinitionError, match=re.escape(message)):
        method.get("/items")(namespace["call"])  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
