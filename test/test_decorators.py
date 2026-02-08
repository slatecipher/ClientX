import pytest
from httpx import Request, Response

import clientx._decorators as decorators_module
from clientx._client import ClientX
from clientx._decorators import ApiMethod, method
from clientx._endpoint_context import EndpointRegister


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
    sent: dict[str, object] = {}

    def fake_send(method: str, path: str, **request) -> Response:
        sent["method"] = method
        sent["path"] = path
        sent["request"] = request
        return Response(200, request=Request(method, f"https://example.test{path}"), json={"id": 42})

    monkeypatch.setattr(api, "send", fake_send)

    response = api.get_item("42")

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert sent["method"] == "GET"
    assert sent["path"] == "/v1/items/42"
    assert sent["request"] == {}
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
