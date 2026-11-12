from collections.abc import Iterator
from typing import Annotated

import pytest
from httpx2 import HTTPStatusError, Request, Response

import clientx._decorators as decorators_module
from clientx import Body, Header
from clientx._client import ClientX
from clientx._decorators import ApiMethod, method
from clientx.decoders import StreamLinesDecoder
from clientx.exceptions import (
    EndpointNameConflictError,
    MissingPathArgumentsError,
    PathTemplateError,
    PathValueError,
)


def test_api_method_registers_endpoint_and_returns_response(endpoint_of, mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    response = API("https://example.test", transport=mock_transport(sent, json={"id": 42})).get_item("42")

    assert isinstance(response, Response)
    assert response.json() == {"id": 42}
    [request] = sent
    assert (request.method, str(request.url), request.content) == ("GET", "https://example.test/v1/items/42", b"")
    endpoint = endpoint_of(API.get_item)
    assert endpoint.method == "GET"
    assert str(endpoint.path) == "/v1/items/{item_id}"


def test_api_method_returns_none_for_none_annotation(mock_transport):
    class API(ClientX):
        @ApiMethod("POST")("/v1/items")
        def create_item(self, json: dict[str, int]) -> None: ...

    api = API("https://example.test", transport=mock_transport(status=201))

    assert api.create_item({"id": 1}) is None


def test_api_method_decodes_non_response_return(mock_transport):
    def decode_count(response: Response) -> int:
        return int(response.json()["count"])

    class API(ClientX):
        @ApiMethod("GET")("/v1/count", decoder=decode_count)
        def get_count(self) -> int: ...

    api = API("https://example.test", transport=mock_transport(json={"count": 7}))

    assert api.get_count() == 7


def test_api_method_runs_decoder_for_response_return(mock_transport):
    def checked(response: Response) -> Response:
        response.raise_for_status()
        return response

    class API(ClientX):
        @ApiMethod("GET")("/v1/items", decoder=checked)
        def list_items(self) -> Response: ...

    # With the built-in check off, the decoder sees the 404 and raises it itself.
    api = API("https://example.test", raise_for_status=False, transport=mock_transport(status=404))

    with pytest.raises(HTTPStatusError):
        api.list_items()


def test_api_method_runs_decoder_for_none_return(mock_transport):
    calls: list[int] = []

    def record(response: Response) -> None:
        calls.append(response.status_code)

    class API(ClientX):
        @ApiMethod("DELETE")("/v1/items/{item_id}", decoder=record)
        def delete_item(self, item_id: str) -> None: ...

    api = API("https://example.test", transport=mock_transport(status=204))

    assert api.delete_item("1") is None
    assert calls == [204]


def test_api_method_streams_when_decoder_requests_it(endpoint_of, mock_transport):
    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder())
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test", transport=mock_transport(content=b"a\nb\n"))

    assert endpoint_of(API.stream).stream is True
    assert list(api.stream()) == ["a", "b"]


def test_api_method_applies_endpoint_timeout(mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @ApiMethod("GET")("/v1/items", timeout=12.5)
        def list_items(self) -> Response: ...

        @ApiMethod("GET")("/v1/users")
        def list_users(self) -> Response: ...

    api = API("https://example.test", timeout=3.0, transport=mock_transport(sent))
    api.list_items()
    api.list_users()

    # The endpoint's timeout wins; an endpoint without one uses the client's.
    assert [request.extensions["timeout"]["read"] for request in sent] == [12.5, 3.0]


def test_api_method_applies_timeout_to_streamed_requests(mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @ApiMethod("GET")("/v1/stream", decoder=StreamLinesDecoder(), timeout=15.0)
        def stream(self) -> Iterator[str]: ...

    api = API("https://example.test", transport=mock_transport(sent, content=b"ok\n"))

    assert list(api.stream()) == ["ok"]
    assert sent[0].extensions["timeout"]["read"] == 15.0


def test_api_method_calls_deprecation_handler(mock_transport):
    calls = {"count": 0}

    def deprecated() -> None:
        calls["count"] += 1

    class API(ClientX):
        @ApiMethod("GET")("/v1/status", deprecated=deprecated)
        def get_status(self) -> Response: ...

    API("https://example.test", transport=mock_transport()).get_status()

    assert calls["count"] == 1


def test_api_method_registers_endpoint_tags(endpoint_of):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items", tags=["catalog", "public"])
        def list_items(self) -> Response: ...

    api = API("https://example.test")

    endpoint = endpoint_of(API.list_items)

    assert endpoint.method == "GET"
    assert str(endpoint.path) == "/v1/items"
    assert endpoint.tags == ["catalog", "public"]
    assert api is not None


def test_api_method_raises_internal_error_when_type_checks_are_forced_false(monkeypatch, mock_transport):
    class API(ClientX):
        @ApiMethod("GET")("/v1/items/{item_id}")
        def get_item(self, item_id: str) -> Response: ...

    api = API("https://example.test", transport=mock_transport())

    monkeypatch.setattr(decorators_module, "is_none_type", lambda _: False)
    monkeypatch.setattr(decorators_module, "is_response_type", lambda _: False)

    with pytest.raises(RuntimeError, match="Internal error: decoder was None for a decodable return type."):
        api.get_item("42")


def test_the_path_defaults_to_the_base_url(endpoint_of, mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @method.get()
        def root(self) -> Response: ...

    API("https://api.example.com/v1/", transport=mock_transport(sent)).root()

    assert str(endpoint_of(API.root).path) == ""
    assert [str(request.url) for request in sent] == ["https://api.example.com/v1/"]


def test_method_container_exposes_http_methods():
    assert method.delete.method == "DELETE"
    assert method.get.method == "GET"
    assert method.head.method == "HEAD"
    assert method.options.method == "OPTIONS"
    assert method.patch.method == "PATCH"
    assert method.post.method == "POST"
    assert method.put.method == "PUT"


def test_endpoint_can_be_named_send(mock_transport):
    sent: list[Request] = []

    class MessagesClient(ClientX):
        @method.post("/messages")
        def send(self, json: dict[str, str]) -> Response: ...

    client = MessagesClient("https://example.test", transport=mock_transport(sent, status=201))

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


def test_the_client_parameter_can_have_any_name(mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @method.get("/items/{item_id}")
        def item(this, item_id: int, params: dict[str, str]) -> Response: ...  # noqa: N805

    api = API("https://api.example.com", transport=mock_transport(sent))
    api.item(3, params={"q": "x"})

    [request] = sent
    assert str(request.url) == "https://api.example.com/items/3?q=x"


def test_a_placeholder_without_a_parameter_raises_when_the_class_is_defined():
    with pytest.raises(MissingPathArgumentsError, match=r"'/users/\{user_id\}': user_id"):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @method.get("/users/{user_id}")
            def user(self, uid: int) -> Response: ...


def test_path_values_cant_change_the_path(mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @method.get("/users/{name}/posts")
        def posts(self, name: str) -> Response: ...

        @method.get("/repos/{repo}/contents/{file_path:path}")
        def contents(self, repo: str, file_path: str) -> Response: ...

    api = API("https://api.example.com/v1/", transport=mock_transport(sent))
    api.posts("../admin?x=1")
    api.contents("clientx", "docs/guide.md")

    assert [request.url.raw_path for request in sent] == [
        b"/v1/users/..%2Fadmin%3Fx%3D1/posts",
        b"/v1/repos/clientx/contents/docs/guide.md",
    ]


@pytest.mark.parametrize("user_id", ["", None])
def test_an_empty_or_none_path_value_raises_before_sending(mock_transport, user_id: str | None):
    sent: list[Request] = []

    class API(ClientX):
        @method.delete("/users/{user_id}")
        def remove(self, user_id: str | None) -> None: ...

    # Sent as is, `""` would delete `/users/` and `None` would delete `/users/null`.
    with pytest.raises(PathValueError, match=r"Can't fill \{user_id\} in '/users/\{user_id\}'"):
        API("https://api.example.com", transport=mock_transport(sent)).remove(user_id)
    assert sent == []


def test_an_unknown_path_converter_raises_when_the_class_is_defined():
    with pytest.raises(PathTemplateError, match="unknown converter"):

        class API(ClientX):  # pyright: ignore[reportUnusedClass]
            @method.get("/users/{user_id:int}")
            def user(self, user_id: int) -> Response: ...


def test_arguments_for_the_same_part_merge_in_parameter_order(mock_transport):
    sent: list[Request] = []

    class API(ClientX):
        @method.post("/items")
        def create(
            self,
            headers: dict[str, str],
            request_id: Annotated[str, Header("X-Request-Id")],
            json: dict[str, object],
            body: Annotated[object, Body()],
        ) -> Response: ...

    api = API("https://api.example.com", transport=mock_transport(sent))
    api.create({"X-Request-Id": "from-dict", "X-Other": "kept"}, "from-param", {"a": 1}, [1, 2])

    [request] = sent
    assert request.headers["X-Request-Id"] == "from-param"
    assert request.headers["X-Other"] == "kept"
    assert request.content == b"[1,2]"
