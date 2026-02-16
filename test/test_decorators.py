from collections.abc import Iterator
from typing import TypedDict

import pytest
from httpx import Request, Response

import clientx._decorators as decorators_module
from clientx._client import ClientX
from clientx._decorators import ApiMethod, method
from clientx._endpoint_context import EndpointRegister
from clientx.decoders import StreamLinesDecoder


class SentCapture(TypedDict):
    method: str
    path: str
    request: dict[str, object]
    stream: bool


@pytest.fixture(autouse=True)
def reset_endpoint_registry():
    original = list(EndpointRegister.registry)
    EndpointRegister.registry = []
    try:
        yield
    finally:
        EndpointRegister.registry = original


def test_api_method_registers_endpoint_and_returns_response(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(method: str, path: str, stream: bool, **request) -> Response:
        sent["method"] = method
        sent["path"] = path
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), json={"id": 42})

    monkeypatch.setattr(api, "send", fake_send)

    response = api.get_item("42")

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert sent["method"] == "GET"
    assert sent["path"] == "/v1/items/42"
    assert sent["request"] == {}
    assert sent["stream"] is False
    assert len(EndpointRegister.registry) == 1
    assert EndpointRegister.registry[0].method == "GET"
    assert str(EndpointRegister.registry[0].path) == "/v1/items/{item_id}"


def test_api_method_returns_none_for_none_annotation(monkeypatch):
    class API(ClientX):
        @ApiMethod("POST")("/v1/items")
        def create_item(self, json: dict[str, int]) -> None: ...

    api = API("https://example.test")

    def fake_send(method: str, path: str, **request) -> Response:
        return Response(201, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(api, "send", fake_send)

    result = api.create_item({"id": 1})

    assert result is None


def test_api_method_decodes_non_response_return(monkeypatch):
    def decode_count(response: Response) -> int:
        return int(response.json()["count"])

    class API(ClientX):
        @ApiMethod("GET")("/v1/count", decoder=decode_count)
        def get_count(self) -> int: ...

    api = API("https://example.test")

    def fake_send(method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"), json={"count": 7})

    monkeypatch.setattr(api, "send", fake_send)

    result = api.get_count()

    assert result == 7


def test_api_method_uses_stream_send_for_stream_decoder(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder(), stream=True)
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(method: str, path: str, stream: bool, **request) -> Response:
        sent["method"] = method
        sent["path"] = path
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), content=b"ok\n")

    monkeypatch.setattr(api, "send", fake_send)

    result = api.stream()

    assert list(result) == ["ok"]
    assert sent["stream"] is True
    assert "timeout" not in sent["request"]


def test_api_method_defaults_stream_to_false():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items")
        def list_items(self) -> Response: ...

    endpoint = EndpointRegister.registry[-1]

    assert endpoint.stream is False


def test_api_method_defaults_timeout_to_none():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items")
        def list_items(self) -> Response: ...

    endpoint = EndpointRegister.registry[-1]

    assert endpoint.timeout is None


def test_api_method_applies_endpoint_timeout(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items", timeout=12.5)
        def list_items(self) -> Response: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(method: str, path: str, stream: bool, **request) -> Response:
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(api, "send", fake_send)

    api.list_items()

    assert sent["request"]["timeout"] == 12.5


def test_api_method_prefers_explicit_timeout_over_stream_default(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder(), stream=True, timeout=15.0)
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test")
    sent: SentCapture = {"method": "", "path": "", "request": {}, "stream": False}

    def fake_send(method: str, path: str, stream: bool, **request) -> Response:
        sent["request"] = request
        sent["stream"] = stream
        return Response(200, request=Request(method, f"https://example.test{path}"), content=b"ok\n")

    monkeypatch.setattr(api, "send", fake_send)

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

    def fake_send(method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(api, "send", fake_send)

    api.get_status()

    assert calls["count"] == 1


def test_api_method_registers_endpoint_tags():
    class API(ClientX):
        @ApiMethod("GET")("/v1/items", tags=["catalog", "public"])
        def list_items(self) -> Response: ...

    api = API("https://example.test")

    endpoint = EndpointRegister.registry[-1]

    assert endpoint.method == "GET"
    assert str(endpoint.path) == "/v1/items"
    assert endpoint.tags == ["catalog", "public"]
    assert api is not None


def test_api_method_raises_internal_error_when_type_checks_are_forced_false(monkeypatch):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    api = API("https://example.test")

    def fake_send(method: str, path: str, **request) -> Response:
        return Response(200, request=Request(method, f"https://example.test{path}"))

    monkeypatch.setattr(api, "send", fake_send)
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
