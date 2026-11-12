import inspect
import warnings
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, cast
from uuid import UUID

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from clientx import Body, File, Form, Header, Query, Response
from clientx._annotations import DumpConfig, Part
from clientx._client import ClientX
from clientx._endpoint_context import Endpoint
from clientx._request_factory import ArgumentCursor, ModelExtractor, RequestFactory
from clientx.exceptions import UnconsumableArgumentError
from clientx.methods import get, patch, post


class Payload(BaseModel):
    headers: Annotated[dict[str, str], Header()]
    params: Annotated[dict[str, int], Query()]
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
    # Models are dumped by alias.
    assert spec.parts["json"] == {"payload": "d-1"}


def test_request_factory_uses_section_annotation_on_parameter():
    endpoint = Endpoint("POST", "/v1/items")

    def handler(self, payload: Annotated[Payload, Body()]) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(payload,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["json"] == {"headers": {"token": "t-1"}, "params": {"q": 1}, "payload": "d-1"}


def test_request_factory_applies_part_dump_config():
    endpoint = Endpoint("POST", "/v1/items")

    class DataPayload(BaseModel):
        data: str
        optional: str | None = None

    def handler(
        self,
        payload: Annotated[
            DataPayload,
            Form(dump_config=DumpConfig(exclude_none=True)),
        ],
    ) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(DataPayload(data="d-1"),), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["data"] == {"data": "d-1"}


def test_merge_request_parts_later_parts_win_without_warnings():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        merged = factory.merge_request_parts(
            [
                {"headers": {"token": "a", "keep": "k"}},
                {"headers": {"token": "b"}},
                {"json": {"a": 1}},
                {"json": "raw"},
            ]
        )

    assert merged == {"headers": {"token": "b", "keep": "k"}, "json": "raw"}


def test_argument_cursor_consumption_and_state():
    def handler(a: int, b: int = 2, c: int = 3): ...

    bound = inspect.signature(handler).bind(1)
    bound.apply_defaults()
    cursor = ArgumentCursor(bound)

    assert cursor.consume("a") == 1
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
        headers: Annotated[dict[str, str], Header()]
        params: Annotated[dict[str, int], Query()]
        data: str

    model = GroupedPayload(headers={"token": "t"}, params={"q": 1}, data="d")
    parts = ModelExtractor()(model, DumpConfig())

    assert parts["headers"] == {"token": "t"}
    assert parts["params"] == {"q": 1}
    assert parts["json"] == {"data": "d"}


def test_request_factory_raises_unconsumable_argument_error():
    endpoint = Endpoint("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, token: str) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("123", "t-1"), kwargs={})

    with pytest.raises(UnconsumableArgumentError, match="Cannot map argument 'token'"):
        RequestFactory(endpoint=endpoint)(arguments)


def test_request_factory_maps_scalar_param_using_part_key():
    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[str, Query("type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("block",), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "block"}


def test_request_factory_maps_enum_param_value_using_part_key():
    class Kind(StrEnum):
        ALLOW = "allow"
        BLOCK = "block"

    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[Kind, Query("type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(Kind.ALLOW,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "allow"}


@pytest.mark.parametrize(("helper", "part"), [(Query, "params"), (Header, "headers"), (Form, "data")])
def test_request_factory_leaves_out_keyed_values_that_are_none(helper: type[Part], part: str):
    endpoint = Endpoint("POST", "/v1/items")

    def handler(
        self,
        kind: Annotated[str | None, helper("kind")] = None,
        page: Annotated[int | None, helper("page")] = None,
    ) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    factory = RequestFactory(endpoint=endpoint)

    assert factory(endpoint.bind(client=client, args=(), kwargs={})).parts == {}
    # Other falsy values are still sent.
    page = "0" if part == "headers" else 0  # httpx2 only takes strings as header values
    assert factory(endpoint.bind(client=client, args=(), kwargs={"page": 0})).parts == {part: {"page": page}}
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
            user_id: Annotated[int | None, Query("userId")] = None,
            trace_id: Annotated[str | None, Header("X-Trace-Id")] = None,
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
        def list_posts(self, filters: Annotated[PostFilters, Query()], headers: dict[str, str | None]) -> Response: ...

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
        def list_items(self, params: dict[str, str], kind: Annotated[str, Query("kind")]) -> Response: ...

    defaults = {"limit": "10"}
    client = ItemsClient("https://example.test", transport=httpx2.MockTransport(handler))
    client.list_items(defaults, "book")

    assert defaults == {"limit": "10"}
    assert str(sent[0].url) == "https://example.test/items?limit=10&kind=book"


type UserIdParam = Annotated[int | None, Query("userId")]
type QueryParam[T] = Annotated[T, Query()]


EVENT_ID = UUID(int=1)
STARTS_AT = datetime(2026, 1, 1, 9, 30)


class Event(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    event_id: UUID
    starts_at: datetime
    price: Decimal


class EventFilters(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    starts_after: datetime
    venue_id: int


class Upload(BaseModel):
    tracing: Annotated[dict[str, str], Header()] = Field(serialization_alias="traceHeaders")
    name: str


def make_recording_client[C: ClientX](client_class: type[C], sent: list[httpx2.Request]) -> C:
    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    return client_class("https://example.test", transport=httpx2.MockTransport(handler))


class EventsClient(ClientX):
    @post("/events")
    def create(self, event: Event) -> Response: ...

    @post("/events/by-name")
    def create_by_field_name(
        self, event: Annotated[Event, Body(dump_config=DumpConfig(by_alias=False))]
    ) -> Response: ...

    @get("/events")
    def search(self, filters: Annotated[EventFilters, Query()]) -> Response: ...

    @post("/uploads")
    def upload(self, upload: Upload) -> Response: ...

    @get("/events/{event_id}")
    def retrieve(
        self,
        event_id: int,
        since: Annotated[datetime, Query("since")],
        request_id: Annotated[UUID, Header("X-Request-Id")],
        page: Annotated[int, Header("X-Page")],
        dry_run: Annotated[bool, Header("X-Dry-Run")],
    ) -> Response: ...


def test_models_are_sent_as_json_values_under_their_aliases():
    sent: list[httpx2.Request] = []
    client = make_recording_client(EventsClient, sent)

    client.create(Event(event_id=EVENT_ID, starts_at=STARTS_AT, price=Decimal("9.99")))
    client.search(EventFilters(starts_after=STARTS_AT, venue_id=7))

    assert sent[0].content == (
        b'{"eventId":"00000000-0000-0000-0000-000000000001","startsAt":"2026-01-01T09:30:00","price":"9.99"}'
    )
    assert str(sent[1].url) == "https://example.test/events?startsAfter=2026-01-01T09%3A30%3A00&venueId=7"


def test_dump_config_overrides_the_json_and_alias_defaults():
    sent: list[httpx2.Request] = []
    client = make_recording_client(EventsClient, sent)

    client.create_by_field_name(Event(event_id=EVENT_ID, starts_at=STARTS_AT, price=Decimal("9.99")))

    assert sent[0].content == (
        b'{"event_id":"00000000-0000-0000-0000-000000000001","starts_at":"2026-01-01T09:30:00","price":"9.99"}'
    )

    endpoint = Endpoint("POST", "/events")

    def handler(self, event: Annotated[Event, Body(dump_config=DumpConfig(mode="python"))]) -> None: ...

    endpoint.func = handler
    event = Event(event_id=EVENT_ID, starts_at=STARTS_AT, price=Decimal("9.99"))
    arguments = endpoint.bind(client=cast(ClientX, object()), args=(event,), kwargs={})

    assert RequestFactory(endpoint=endpoint)(arguments).parts["json"]["startsAt"] == STARTS_AT


def test_model_fields_with_a_serialization_alias_are_routed_by_their_annotation():
    sent: list[httpx2.Request] = []
    client = make_recording_client(EventsClient, sent)

    client.upload(Upload(tracing={"X-Trace-Id": "t-1"}, name="report.pdf"))

    assert sent[0].headers["X-Trace-Id"] == "t-1"
    assert sent[0].content == b'{"name":"report.pdf"}'


def test_single_values_are_sent_as_json_values_and_headers_as_text():
    sent: list[httpx2.Request] = []
    client = make_recording_client(EventsClient, sent)

    client.retrieve(1, STARTS_AT, EVENT_ID, 2, True)

    assert str(sent[0].url) == "https://example.test/events/1?since=2026-01-01T09%3A30%3A00"
    assert sent[0].headers["X-Request-Id"] == "00000000-0000-0000-0000-000000000001"
    assert sent[0].headers["X-Page"] == "2"
    assert sent[0].headers["X-Dry-Run"] == "true"


class SearchClient(ClientX):
    @get("/search")
    def search(
        self,
        query: Annotated[str, Query()],
        tags: Annotated[list[str], Query()],
        request_id: Annotated[str, Header()],
        page: Annotated[int | None, Query()] = None,
        extra: Annotated[dict[str, str] | None, Query()] = None,
    ) -> Response: ...

    @post("/login")
    def login(self, username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Response: ...

    @get("/raw")
    def raw(self, headers: list[tuple[str, str]]) -> Response: ...

    @post("/upload")
    def upload(self, auth: Annotated[str, Header()]) -> Response: ...


def test_single_values_without_a_key_are_sent_under_the_parameter_name():
    sent: list[httpx2.Request] = []
    client = make_recording_client(SearchClient, sent)

    client.search("ada", ["math", "poetry"], "r-1", extra={"lang": "en"})
    client.search("ada", [], "r-2", page=2)

    # A mapping is still merged into the part, and a list repeats the name.
    assert str(sent[0].url) == "https://example.test/search?query=ada&tags=math&tags=poetry&lang=en"
    assert str(sent[1].url) == "https://example.test/search?query=ada&page=2"
    # Header names use hyphens.
    assert sent[0].headers["request-id"] == "r-1"


def test_single_form_fields_and_headers_without_a_key_are_sent_under_the_parameter_name():
    sent: list[httpx2.Request] = []
    client = make_recording_client(SearchClient, sent)

    client.login("ada", "secret")
    client.upload("Bearer t-1")

    assert sent[0].content == b"username=ada&password=secret"
    assert sent[1].headers["auth"] == "Bearer t-1"


def test_parameters_named_after_a_part_are_still_the_whole_part():
    sent: list[httpx2.Request] = []
    client = make_recording_client(SearchClient, sent)

    client.raw([("X-First", "1"), ("X-Second", "2")])

    assert (sent[0].headers["X-First"], sent[0].headers["X-Second"]) == ("1", "2")


class Lookup(BaseModel):
    user_id: Annotated[int, Query()] = Field(alias="userId")
    api_key: Annotated[str, Header("X-Api-Key")]
    request_id: Annotated[str | None, Header()] = None
    note: str


class LookupClient(ClientX):
    @post("/lookups")
    def create(self, lookup: Lookup) -> Response: ...


def test_single_model_fields_are_sent_under_their_key_or_dumped_name():
    sent: list[httpx2.Request] = []
    client = make_recording_client(LookupClient, sent)

    client.create(Lookup(userId=1, api_key="k-1", request_id="r-1", note="hi"))
    client.create(Lookup(userId=2, api_key="k-2", note="hi"))

    assert str(sent[0].url) == "https://example.test/lookups?userId=1"
    assert sent[0].headers["X-Api-Key"] == "k-1"
    assert sent[0].headers["request-id"] == "r-1"
    assert sent[0].content == b'{"note":"hi"}'
    assert "request-id" not in sent[1].headers


class AliasFilters(BaseModel):
    user_id: UserIdParam = None


class AliasClient(ClientX):
    @get("/posts")
    def list_posts(self, user_id: UserIdParam = None, tags: QueryParam[list[str] | None] = None) -> Response: ...

    @get("/posts/filtered")
    def filter_posts(self, filters: AliasFilters) -> Response: ...


def test_markers_in_type_aliases_route_parameters_and_model_fields():
    sent: list[httpx2.Request] = []
    client = make_recording_client(AliasClient, sent)

    client.list_posts(user_id=1, tags=["a", "b"])
    client.filter_posts(AliasFilters(user_id=2))

    assert str(sent[0].url) == "https://example.test/posts?userId=1&tags=a&tags=b"
    assert str(sent[1].url) == "https://example.test/posts/filtered?userId=2"


class PostChanges(BaseModel):
    title: str | None = None
    body: str | None = None


class HelperPost(BaseModel):
    user_id: Annotated[int, Query("userId")]
    trace_id: Annotated[str | None, Header()] = None
    title: str


class HelpersClient(ClientX):
    @get("/posts")
    def search(
        self,
        user_id: Annotated[int | None, Query("userId")] = None,
        tags: Annotated[list[str] | None, Query()] = None,
        authorization: Annotated[str | None, Header("Authorization")] = None,
        request_id: Annotated[str | None, Header()] = None,
    ) -> Response: ...

    @post("/login")
    def login(self, username: Annotated[str, Form()], password: Annotated[str, Form("pass")]) -> Response: ...

    @patch("/posts/{post_id}")
    def update(
        self, post_id: int, changes: Annotated[PostChanges, Body(dump_config=DumpConfig(exclude_unset=True))]
    ) -> Response: ...

    @post("/attachments")
    def attach(self, attachment: Annotated[dict[str, bytes], File()]) -> Response: ...

    @post("/posts")
    def create(self, new_post: HelperPost) -> Response: ...


def test_query_and_header_helpers():
    sent: list[httpx2.Request] = []
    client = make_recording_client(HelpersClient, sent)

    client.search(user_id=1, tags=["a", "b"], authorization="Bearer t-1", request_id="r-1")
    client.search()

    assert str(sent[0].url) == "https://example.test/posts?userId=1&tags=a&tags=b"
    assert (sent[0].headers["Authorization"], sent[0].headers["request-id"]) == ("Bearer t-1", "r-1")
    assert str(sent[1].url) == "https://example.test/posts"
    assert "Authorization" not in sent[1].headers


def test_form_body_and_file_helpers():
    sent: list[httpx2.Request] = []
    client = make_recording_client(HelpersClient, sent)

    client.login("ada", "secret")
    client.update(1, PostChanges(title="New title"))
    client.attach({"report": b"%PDF"})

    assert sent[0].content == b"username=ada&pass=secret"
    assert sent[1].content == b'{"title":"New title"}'
    assert b'name="report"' in sent[2].read()


def test_helpers_on_model_fields():
    sent: list[httpx2.Request] = []
    client = make_recording_client(HelpersClient, sent)

    client.create(HelperPost(user_id=1, trace_id="t-1", title="Hello"))

    assert str(sent[0].url) == "https://example.test/posts?userId=1"
    assert sent[0].headers["trace-id"] == "t-1"
    assert sent[0].content == b'{"title":"Hello"}'
