import inspect
from enum import StrEnum
from typing import Annotated, cast

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import Response
from clientx._annotations import DumpConfig, FieldX, RequestPart
from clientx._client import ClientX
from clientx._endpoint_context import Endpoint
from clientx._request_factory import ArgumentCursor, ModelExtractor, RequestFactory
from clientx.exceptions import UnconsumableArgumentError
from clientx.methods import get, patch


class Payload(BaseModel):
    headers: Annotated[dict[str, str], FieldX(RequestPart.HEADERS)]
    params: Annotated[dict[str, int], FieldX(RequestPart.PARAMS)]
    data: str = Field(alias="payload")


def test_request_factory_builds_request_parts():
    endpoint = Endpoint("GET", "/v1/items/{item_id}")

    def handler(
        self,
        item_id: str,
        payload: Payload,
        params: dict[str, int],
        headers: dict[str, str],
    ) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    arguments = endpoint.bind(
        client=client,
        args=("123", payload, {"limit": 5}, {"header": "h-1"}),
        kwargs={},
    )

    factory = RequestFactory(endpoint=endpoint)
    spec = factory(arguments)

    assert spec.path == "/v1/items/123"
    assert spec.parts["headers"] == {"token": "t-1", "header": "h-1"}
    assert spec.parts["params"] == {"q": 1, "limit": 5}
    assert spec.parts["json"] == {"data": "d-1"}


def test_request_factory_uses_section_annotation_on_parameter():
    endpoint = Endpoint("POST", "/v1/items")

    def handler(self, payload: Annotated[Payload, FieldX(RequestPart.JSON)]) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(payload,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["json"] == {"headers": {"token": "t-1"}, "params": {"q": 1}, "data": "d-1"}


def test_request_factory_applies_fieldx_dump_config():
    endpoint = Endpoint("POST", "/v1/items")

    class DataPayload(BaseModel):
        data: str
        optional: str | None = None

    def handler(
        self,
        payload: Annotated[
            DataPayload,
            FieldX(RequestPart.DATA, dump_config=DumpConfig(exclude_none=True)),
        ],
    ) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(DataPayload(data="d-1"),), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["data"] == {"data": "d-1"}


def test_merge_request_parts_warns_on_shared_dict_keys():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=True)

    with pytest.warns(UserWarning, match="share keys for 'headers'"):
        factory.merge_request_parts(
            [
                {"headers": {"token": "a"}},
                {"headers": {"token": "b", "other": "c"}},
            ]
        )


def test_merge_request_parts_warns_on_full_overwrite():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=True)

    with pytest.warns(UserWarning, match="fully overwritten"):
        factory.merge_request_parts(
            [
                {"json": {"a": 1}},
                {"json": "raw"},
            ]
        )


def test_merge_request_parts_silent_when_disabled():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=False)

    factory.merge_request_parts(
        [
            {"headers": {"token": "a"}},
            {"headers": {"token": "b"}},
            {"json": {"a": 1}},
            {"json": "raw"},
        ]
    )


def test_argument_cursor_consumption_and_state():
    def handler(a: int, b: int = 2, c: int = 3): ...

    bound = inspect.signature(handler).bind(1)
    bound.apply_defaults()
    cursor = ArgumentCursor(bound)

    assert cursor.consume("a") == 1
    assert cursor.consume_optional("a", default=99) == 1
    assert cursor.consume_optional("missing", default=99) == 99
    assert cursor.is_consumed("a") is True
    assert cursor.is_consumed("b") is False
    assert cursor.consumed == {"a": 1}
    assert cursor.bound_copy == {"b": 2, "c": 3}


def test_argument_cursor_consume_errors():
    def handler(a: int): ...

    bound = inspect.signature(handler).bind(1)
    cursor = ArgumentCursor(bound)

    assert cursor.consume("a") == 1
    with pytest.raises(KeyError, match="already consumed"):
        cursor.consume("a")
    with pytest.raises(KeyError, match="not available"):
        cursor.consume("missing")


def test_model_extractor_groups_sections_and_defaults_json():
    class GroupedPayload(BaseModel):
        headers: Annotated[dict[str, str], FieldX(RequestPart.HEADERS)]
        params: Annotated[dict[str, int], FieldX(RequestPart.PARAMS)]
        data: str

    model = GroupedPayload(headers={"token": "t"}, params={"q": 1}, data="d")
    parts = ModelExtractor()(model, DumpConfig())

    assert parts[RequestPart.HEADERS] == {"token": "t"}
    assert parts[RequestPart.PARAMS] == {"q": 1}
    assert parts[RequestPart.JSON] == {"data": "d"}


def test_request_factory_raises_unconsumable_argument_error():
    endpoint = Endpoint("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, token: str) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("123", "t-1"), kwargs={})

    with pytest.raises(UnconsumableArgumentError, match="Cannot map argument 'token'"):
        RequestFactory(endpoint=endpoint)(arguments)


def test_request_factory_maps_scalar_param_using_fieldx_key():
    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[str, FieldX(RequestPart.PARAMS, key="type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("block",), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "block"}


def test_request_factory_maps_enum_param_value_using_fieldx_key():
    class Kind(StrEnum):
        ALLOW = "allow"
        BLOCK = "block"

    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[Kind, FieldX(RequestPart.PARAMS, key="type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(Kind.ALLOW,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "allow"}


@pytest.mark.parametrize("part", [RequestPart.PARAMS, RequestPart.HEADERS, RequestPart.DATA])
def test_request_factory_leaves_out_keyed_values_that_are_none(part: RequestPart):
    endpoint = Endpoint("POST", "/v1/items")

    def handler(
        self,
        kind: Annotated[str | None, FieldX(part, key="kind")] = None,
        page: Annotated[int | None, FieldX(part, key="page")] = None,
    ) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    factory = RequestFactory(endpoint=endpoint)

    assert factory(endpoint.bind(client=client, args=(), kwargs={})).parts == {}
    # Other falsy values are still sent.
    assert factory(endpoint.bind(client=client, args=(), kwargs={"page": 0})).parts == {part: {"page": 0}}
    assert factory(endpoint.bind(client=client, args=("",), kwargs={})).parts == {part: {"kind": ""}}


def test_optional_keyed_values_are_only_sent_when_given():
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    class PostsClient(ClientX):
        @get("/posts")
        def list_posts(
            self,
            user_id: Annotated[int | None, FieldX(RequestPart.PARAMS, key="userId")] = None,
            trace_id: Annotated[str | None, FieldX(RequestPart.HEADERS, key="X-Trace-Id")] = None,
        ) -> Response: ...

    client = PostsClient("https://example.test", transport=httpx2.MockTransport(handler))
    client.list_posts()
    client.list_posts(user_id=1, trace_id="t-1")

    assert [str(request.url) for request in sent] == [
        "https://example.test/posts",
        "https://example.test/posts?userId=1",
    ]
    assert [request.headers.get("X-Trace-Id") for request in sent] == [None, "t-1"]


def test_merge_request_parts_leaves_none_out_of_keyed_parts_but_not_json():
    merged = RequestFactory(endpoint=Endpoint("POST", "/v1/items")).merge_request_parts(
        [
            {"params": {"a": None, "b": 1}},
            {"headers": {"X-A": None, "X-B": "b"}},
            {"data": {"c": None, "d": "d"}},
            {"json": {"e": None}},
        ]
    )

    assert merged == {"params": {"b": 1}, "headers": {"X-B": "b"}, "data": {"d": "d"}, "json": {"e": None}}


def test_none_values_in_mappings_and_models_are_not_sent():
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    class PostFilters(BaseModel):
        user_id: int | None = None
        topic: str | None = None

    class PostChanges(BaseModel):
        title: str | None = None

    class PostsClient(ClientX):
        @get("/posts")
        def list_posts(
            self, filters: Annotated[PostFilters, FieldX(RequestPart.PARAMS)], headers: dict[str, str | None]
        ) -> Response: ...

        @patch("/posts/1")
        def update_post(self, changes: PostChanges) -> Response: ...

    client = PostsClient("https://example.test", transport=httpx2.MockTransport(handler))
    client.list_posts(PostFilters(topic="news"), {"X-Trace-Id": None, "X-Client": "docs"})
    client.update_post(PostChanges())

    assert str(sent[0].url) == "https://example.test/posts?topic=news"
    assert "X-Trace-Id" not in sent[0].headers
    assert sent[0].headers["X-Client"] == "docs"
    # JSON can represent null, so a JSON body keeps it.
    assert sent[1].content == b'{"title":null}'


def test_merging_request_parts_never_changes_the_callers_dict():
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    class ItemsClient(ClientX):
        @get("/items")
        def list_items(
            self, params: dict[str, str], kind: Annotated[str, FieldX(RequestPart.PARAMS, key="kind")]
        ) -> Response: ...

    defaults = {"limit": "10"}
    client = ItemsClient("https://example.test", transport=httpx2.MockTransport(handler))
    client.list_items(defaults, "book")

    assert defaults == {"limit": "10"}
    assert str(sent[0].url) == "https://example.test/items?limit=10&kind=book"
