import inspect
from typing import cast

from clientx._call_context import CallContext
from clientx._client import ClientX
from clientx._endpoint_context import EndpointContext


def test_call_context_binds_args_and_defaults():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, include_meta: bool = False) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    ctx = CallContext.from_call(endpoint=endpoint, client=client, args=("123",), kwargs={})

    assert ctx.endpoint is endpoint
    assert ctx.client is client
    assert ctx.bound.signature == inspect.signature(handler)
    assert ctx.bound.arguments["item_id"] == "123"
    assert ctx.bound.arguments["include_meta"] is False


def test_call_context_client_is_explicit():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, limit: int = 10) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    ctx = CallContext.from_call(endpoint=endpoint, client=client, args=("abc",), kwargs={})

    assert ctx.client is client
    assert ctx.bound.arguments["item_id"] == "abc"
    assert ctx.bound.arguments["limit"] == 10


def test_call_context_binds_keyword_arguments():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    ctx = CallContext.from_call(endpoint=endpoint, client=client, args=(), kwargs={"item_id": "1"})

    assert ctx.client is client
    assert ctx.bound.arguments["item_id"] == "1"
