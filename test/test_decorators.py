import json
from collections.abc import Iterator
from typing import Annotated, get_overloads

import pytest
from httpx2 import HTTPStatusError, Request, Response
from pydantic import BaseModel, Field, RootModel

import clientx._decorators as decorators_module
from clientx import Body, DumpConfig, Header, method
from clientx._client import ClientX
from clientx._decorators import ApiMethod, DecodedEndpointDecorator, RawEndpointDecorator
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


def test_type_checker_messages_name_the_fix():
    # docs/decoders.md and llms.txt quote checker messages that use these names, such as
    # 'Type "User" is not assignable to constrained type variable "ResponseOrNone"'.
    # Each protocol has three overloads (def, async def, def again), and each must use the same names.
    raw = [
        [param.__name__ for param in overload.__type_params__]
        for overload in get_overloads(RawEndpointDecorator.__call__)
    ]
    decoded = [
        [param.__name__ for param in overload.__type_params__]
        for overload in get_overloads(DecodedEndpointDecorator.__call__)
    ]

    assert raw == [["C", "Q", "ResponseOrNone"]] * 3
    assert decoded == [["C", "Q", "DecoderOutput"]] * 3


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


def test_endpoints_can_be_named_client_and_user_agent(mock_transport):
    sent: list[Request] = []

    class EchoClient(ClientX):
        @method.get("/user-agent")
        def user_agent(self) -> Response: ...

        @method.get("/client")
        def client(self) -> Response: ...

    api = EchoClient("https://example.test", transport=mock_transport(sent))
    api.user_agent()
    api.client()

    assert [request.url.path for request in sent] == ["/user-agent", "/client"]


@pytest.mark.parametrize("name", ["close", "__clientx_client__", "__clientx_user_agent__", "__enter__"])
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


class Thing(BaseModel):
    thing_id: int = Field(alias="thingId")
    note: str | None = None


class Things(RootModel[list[Thing]]):
    pass


def test_lists_and_dicts_of_models_are_sent_as_json(mock_transport):
    class API(ClientX):
        @method.post("/bulk")
        def bulk(self, json: list[Thing]) -> Response: ...

        @method.post("/by-key")
        def by_key(self, things: Annotated[dict[str, Thing], Body()]) -> Response: ...

        @method.post("/changes")
        def changes(
            self, things: Annotated[list[Thing], Body(dump_config=DumpConfig(exclude_unset=True))]
        ) -> Response: ...

        # Pydantic applies `exclude` to the list itself, so "__all__" reaches each item (docs/requests.md).
        @method.post("/without-notes")
        def without_notes(
            self,
            things: Annotated[list[Thing], Body(dump_config=DumpConfig(exclude={"__all__": {"note"}}))],
        ) -> Response: ...

        @method.post("/plain")
        def plain(self, json: dict[str, object]) -> Response: ...

    sent: list[Request] = []
    api = API("https://api.example.com", transport=mock_transport(sent))
    items = [Thing(thingId=1)]
    api.bulk(items)
    api.by_key({"a": Thing(thingId=2)})
    api.changes([Thing(thingId=3)])
    api.without_notes([Thing(thingId=5, note="x")])
    api.plain({"name": "Ada", "tags": None})

    assert [json.loads(request.content) for request in sent] == [
        [{"thingId": 1, "note": None}],
        {"a": {"thingId": 2, "note": None}},
        [{"thingId": 3}],
        [{"thingId": 5}],
        {"name": "Ada", "tags": None},
    ]
    assert items == [Thing(thingId=1)]  # The caller's list isn't changed.


def test_a_root_model_is_the_whole_json_body(mock_transport):
    class API(ClientX):
        @method.post("/bulk")
        def bulk(self, things: Things) -> Response: ...

    sent: list[Request] = []
    API("https://api.example.com", transport=mock_transport(sent)).bulk(Things([Thing(thingId=4, note="x")]))

    assert json.loads(sent[0].content) == [{"thingId": 4, "note": "x"}]
