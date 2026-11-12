from collections.abc import Iterator
from typing import TypedDict

import httpx2
import pytest
from httpx2 import HTTPStatusError, Request, Response

import clientx._decorators as decorators_module
from clientx._client import ClientX
from clientx._decorators import ApiMethod, method
from clientx._endpoint_context import Endpoint
from clientx._registry import endpoint_for
from clientx.decoders import StreamLinesDecoder
from clientx.exceptions import EndpointNameConflictError, MissingPathArgumentsError


def endpoint_of(function: object) -> Endpoint:
    endpoint = endpoint_for(function)
    assert endpoint is not None
    return endpoint


class SentCapture(TypedDict):
    method: str
    path: str
    request: dict[str, object]
    stream: bool


def test_api_method_registers_endpoint_and_returns_response(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(client: ClientX, method: str, path: str, stream: bool, **request) -> Response:
        sent["method"] = method
        sent["path"] = path
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), json={"id": 42})

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    response = api.get_item("42")

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert sent["method"] == "GET"
    assert sent["path"] == "/v1/items/42"
    assert sent["request"] == {}
    assert sent["stream"] is False
    endpoint = endpoint_of(API.get_item)
    assert endpoint.method == "GET"
    assert str(endpoint.path) == "/v1/items/{item_id}"


def test_api_method_returns_none_for_none_annotation(monkeypatch):
    class API(ClientX):
        @ApiMethod("POST")("/v1/items")
        def create_item(self, json: dict[str, int]) -> None: ...

    api = API("https://example.test")

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(201, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    result = api.create_item({"id": 1})

    assert result is None


def test_api_method_decodes_non_response_return(monkeypatch):
    def decode_count(response: Response) -> int:
        return int(response.json()["count"])

    class API(ClientX):
        @ApiMethod("GET")("/v1/count", decoder=decode_count)
        def get_count(self) -> int: ...

    api = API("https://example.test")

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"), json={"count": 7})

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    result = api.get_count()

    assert result == 7


def test_api_method_runs_decoder_for_response_return(monkeypatch):
    def checked(response: Response) -> Response:
        response.raise_for_status()
        return response

    class API(ClientX):
        @ApiMethod("GET")("/v1/items", decoder=checked)
        def list_items(self) -> Response: ...

    # With the built-in check off, the decoder sees the 404 and raises it itself.
    api = API("https://example.test", raise_for_status=False)

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(404, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    with pytest.raises(HTTPStatusError):
        api.list_items()


def test_api_method_runs_decoder_for_none_return(monkeypatch):
    calls: list[int] = []

    def record(response: Response) -> None:
        calls.append(response.status_code)

    class API(ClientX):
        @ApiMethod("DELETE")("/v1/items/{item_id}", decoder=record)
        def delete_item(self, item_id: str) -> None: ...

    api = API("https://example.test")

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(204, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    assert api.delete_item("1") is None
    assert calls == [204]


def test_api_method_uses_stream_send_for_stream_decoder(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder())
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(client: ClientX, method: str, path: str, stream: bool, **request) -> Response:
        sent["method"] = method
        sent["path"] = path
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), content=b"ok\n")

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    result = api.stream()

    assert list(result) == ["ok"]
    assert sent["stream"] is True
    assert "timeout" not in sent["request"]


def test_api_method_streams_when_decoder_requests_it(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder())
        def stream(self) -> Iterator[str]: ...

    endpoint = endpoint_of(API.stream)
    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(client: ClientX, method: str, path: str, stream: bool, **request) -> Response:
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), content=b"a\nb\n")

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    assert list(api.stream()) == ["a", "b"]
    assert endpoint.stream is True
    assert sent["stream"] is True


def test_api_method_defaults_stream_to_false():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items")
        def list_items(self) -> Response: ...

    endpoint = endpoint_of(API.list_items)

    assert endpoint.stream is False


def test_api_method_defaults_timeout_to_none():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items")
        def list_items(self) -> Response: ...

    endpoint = endpoint_of(API.list_items)

    assert endpoint.timeout is None


def test_api_method_applies_endpoint_timeout(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items", timeout=12.5)
        def list_items(self) -> Response: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(client: ClientX, method: str, path: str, stream: bool, **request) -> Response:
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    api.list_items()

    assert sent["request"]["timeout"] == 12.5


def test_api_method_applies_timeout_to_streamed_requests(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder(), timeout=15.0)
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(client: ClientX, method: str, path: str, stream: bool, **request) -> Response:
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), content=b"ok\n")

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    list(api.stream())

    assert sent["stream"] is True
    assert sent["request"]["timeout"] == 15.0


def test_api_method_calls_deprecation_handler(monkeypatch):
    calls = {"count": 0}

    def deprecated() -> None:
        calls["count"] += 1

    class API(ClientX):
        @ApiMethod("GET")("/v1/status", deprecated=deprecated)
        def get_status(self) -> Response: ...

    api = API("https://example.test")

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)

    api.get_status()

    assert calls["count"] == 1


def test_api_method_registers_endpoint_tags():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items", tags=["catalog", "public"])
        def list_items(self) -> Response: ...

    api = API("https://example.test")

    endpoint = endpoint_of(API.list_items)

    assert endpoint.method == "GET"
    assert str(endpoint.path) == "/v1/items"
    assert endpoint.tags == ["catalog", "public"]
    assert api is not None


def test_api_method_raises_internal_error_when_type_checks_are_forced_false(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    api = API("https://example.test")

    def fake_send(client: ClientX, method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(decorators_module, "send_request", fake_send)
    monkeypatch.setattr(decorators_module, "is_none_type", lambda _: False)
    monkeypatch.setattr(decorators_module, "is_response_type", lambda _: False)

    with pytest.raises(RuntimeError, match="Internal error: decoder was None for a decodable return type."):
        api.get_item("42")


def test_method_container_exposes_http_methods():
    assert method.delete.method == "DELETE"
    assert method.get.method == "GET"
    assert method.head.method == "HEAD"
    assert method.options.method == "OPTIONS"
    assert method.patch.method == "PATCH"
    assert method.post.method == "POST"
    assert method.put.method == "PUT"


def test_endpoint_can_be_named_send():
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> Response:
        sent.append(request)
        return Response(201)

    class MessagesClient(ClientX):
        @method.post("/messages")
        def send(self, json: dict[str, str]) -> Response: ...

    client = MessagesClient("https://example.test", transport=httpx2.MockTransport(handler))

    assert client.send({"text": "hi"}).status_code == 201
    assert [(request.method, request.url.path, request.content) for request in sent] == [
        ("POST", "/messages", b'{"text":"hi"}')
    ]


def test_endpoint_named_user_agent_is_rejected_when_the_class_is_defined():
    with pytest.raises(EndpointNameConflictError) as excinfo:

        class ProfileClient(ClientX):
            @method.get("/user-agent")
            def user_agent(self) -> Response: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    message = str(excinfo.value)
    assert "ProfileClient.user_agent" in message
    assert "can't be named 'user_agent'" in message


@pytest.mark.parametrize("name", ["user_agent", "client", "_user_agent", "_default_user_agent", "__enter__"])
def test_endpoint_cannot_use_a_name_clientx_already_uses(name: str):
    def endpoint(self: ClientX) -> Response: ...

    endpoint.__name__ = endpoint.__qualname__ = name

    with pytest.raises(EndpointNameConflictError, match=f"'Dynamic.{name}' .* can't be named '{name}'"):
        type("Dynamic", (ClientX,), {name: method.get("/items")(endpoint)})


def test_the_client_parameter_can_have_any_name():
    sent: list[Request] = []

    class API(ClientX):
        @method.get("/items/{item_id}")
        def item(this, item_id: int, params: dict[str, str]) -> Response: ...  # noqa: N805

    api = API(
        "https://api.example.com", transport=httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(200))
    )
    api.item(3, params={"q": "x"})

    [request] = sent
    assert str(request.url) == "https://api.example.com/items/3?q=x"


def test_a_placeholder_without_a_parameter_raises_when_the_class_is_defined():
    with pytest.raises(MissingPathArgumentsError, match=r"'/users/\{user_id\}': user_id"):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @method.get("/users/{user_id}")
            def user(self, uid: int) -> Response: ...
