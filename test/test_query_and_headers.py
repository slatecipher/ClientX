"""Query parameters and headers: placement, names and value text."""

import datetime
import enum
import inspect
import json
import re
from collections.abc import Callable, Collection, Sequence
from typing import Annotated, Any, Literal, NewType, Optional

import httpx2
import pytest
from pydantic import BaseModel, Field, PlainSerializer

from clientx import ArgumentError, ClientX, DefinitionError, Form, Header, Json, Query, Send, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class Color(enum.Enum):
    RED = "red"


class Filters(BaseModel):
    status: str


type HeaderValue = Annotated[str, Header()]
type HeaderParam[T] = Annotated[T, Header()]
type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


def header_names(request: httpx2.Request) -> list[str]:
    """Return the request's header names as sent, in their own case."""
    return [name.decode() for name, _ in request.headers.raw]


# Where a parameter goes


@pytest.mark.parametrize(
    ("parameter", "example"),
    [
        pytest.param("page: int = 1", "page: Annotated[int, Query()]", id="plain value"),
        pytest.param("filters: Filters", "filters: Annotated[Filters, Json()]", id="model"),
    ],
)
def test_a_parameter_without_a_helper_fails(parameter: str, example: str) -> None:
    # ClientX doesn't guess where a parameter goes: only a path placeholder's
    # parameter goes without a helper.
    source = f"class API(ClientX):\n    @method.get('/items')\n    def search(self, {parameter}) -> None: ..."
    with pytest.raises(DefinitionError, match=re.escape("needs a helper that says where it goes")) as raised:
        exec(source, {"ClientX": ClientX, "method": method, "Filters": Filters})  # noqa: S102
    assert f"as in {example}." in str(raised.value)


def test_query_values_are_sent_as_text(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            page: Annotated[int, Query()] = 1,
            flag: Annotated[bool, Query()] = False,
            color: Annotated[Color, Query()] = Color.RED,
            since: Annotated[datetime.datetime | None, Query()] = None,
            kind: Annotated[Literal["a", "b"], Query()] = "a",
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(
        page=2, flag=True, since=datetime.datetime(2026, 11, 17, 9, 30), kind="b"
    )
    assert only_request(sent).url.query.decode() == "page=2&flag=true&color=red&since=2026-11-17T09%3A30%3A00&kind=b"


def test_defaults_are_sent_and_none_is_left_out(mock_transport: MockTransport) -> None:
    # Defaults are sent, as a Python call would use them (#135); `None` lets the
    # server decide.
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            page: Annotated[int, Query()] = 1,
            q: Annotated[str | None, Query()] = None,
            opt: Annotated[Optional[int], Query()] = None,  # noqa: UP045
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search()
    assert only_request(sent).url.query.decode() == "page=1"


def test_a_recursive_type_alias_works(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/values")
        def store(self, value: Annotated[JsonValue, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).store({"k": [1]})
    assert json.loads(only_request(sent).content) == {"k": [1]}


def test_the_last_helper_wins(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            moved: Annotated[str, Query(), Header()],
            limited: Annotated[int, Field(gt=0), Query(alias="q")],
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search("to-a-header", 5)
    request = only_request(sent)
    assert request.url.query.decode() == "q=5"
    assert request.headers["moved"] == "to-a-header"


# Query parameters


def test_a_query_parameter_is_sent_under_its_alias(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, term: Annotated[str, Query(alias="searchTerm")]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search("t")
    assert only_request(sent).url.query.decode() == "searchTerm=t"


def test_a_list_repeats_its_query_parameter(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            tags: Annotated[list[str] | None, Query()] = None,
            ids: Annotated[tuple[int, ...], Query()] = (),
        ) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.search(tags=["a", "b"], ids=(1, 2))
    api.search()
    assert [request.url.query.decode() for request in sent] == ["tags=a&tags=b&ids=1&ids=2", ""]


def test_the_clients_own_query_parameters_are_kept(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, page: Annotated[int, Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent), params={"api_key": "k"}).search(2)
    assert only_request(sent).url.query.decode() == "api_key=k&page=2"


# Headers


def test_a_header_is_named_after_its_parameter_with_hyphens(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            x_request_id: Annotated[str | None, Header()] = None,
            page: Annotated[int, Header(alias="X-Page")] = 1,
            dry: Annotated[bool, Header()] = False,
            tone: Annotated[Color, Header()] = Color.RED,
            from_alias: HeaderValue = "via a type alias",
        ) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.search(x_request_id="abc", page=3, dry=True)
    api.search()
    with_id, without = sent
    assert {name: with_id.headers[name] for name in ("x-request-id", "X-Page", "dry", "tone", "from-alias")} == {
        "x-request-id": "abc",
        "X-Page": "3",
        "dry": "true",
        "tone": "red",
        "from-alias": "via a type alias",
    }
    assert "X-Page" in header_names(with_id)
    assert "x-request-id" not in without.headers


def test_the_clients_own_headers_are_kept(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, x_trace: Annotated[str, Header()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent), headers={"X-Client": "1"}).search("t")
    request = only_request(sent)
    assert (request.headers["X-Client"], request.headers["x-trace"]) == ("1", "t")


def test_a_generic_type_alias_carries_its_helper(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, trace_id: HeaderParam[str], attempt: HeaderParam[int] = 1) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search("t-1")
    request = only_request(sent)
    assert (request.headers["trace-id"], request.headers["attempt"], request.url.query) == ("t-1", "1", b"")


# Where a helper can be


@pytest.mark.parametrize(
    "annotation",
    [
        # Python supports `|` on Annotated; pyright doesn't model it outside an
        # annotation.
        Annotated[str, Header()] | None,  # pyright: ignore[reportOperatorIssue]
        list[Annotated[int, Query()]],
    ],
    ids=["union", "list item"],
)
def test_a_helper_inside_a_parameters_type_fails(annotation: Any) -> None:
    with pytest.raises(DefinitionError, match=re.escape("has a helper inside its type")):

        class API(ClientX):
            @method.get("/items")
            def search(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_plain_field_inside_a_type_isnt_a_helper(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, counts: Annotated[list[Annotated[int, Field(gt=0)]], Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create([1, 2])
    assert json.loads(only_request(sent).content) == [1, 2]


@pytest.mark.parametrize(
    ("path", "annotation"),
    [
        ("/items", Annotated[int, Query(default=1)]),
        ("/items", Annotated[str, Header(default_factory=str)]),
    ],
    ids=["Query(default=)", "Header(default_factory=)"],
)
def test_a_default_inside_a_helper_fails(path: str, annotation: Any) -> None:
    with pytest.raises(DefinitionError, match=re.escape("has a default inside its helper")):

        class API(ClientX):
            @method.get(path)
            def search(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_query_with_ellipsis_isnt_a_default(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, page: Annotated[int, Query(...)]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(3)
    assert only_request(sent).url.query.decode() == "page=3"


# What a query or header value can be: the plain-value allow-list


class Price:
    def __str__(self) -> str:
        return "9.90 EUR"


OrderId = NewType("OrderId", int)


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        pytest.param(
            Annotated[Price, Query()],
            "goes to the query string, which takes a plain value or a collection of them. A plain value is one of "
            "str, int, float, bool, Enum, date, datetime, time, UUID, Decimal, bytes, or Any",
            id="your own class",
        ),
        pytest.param(
            Annotated[list[str], Header()], "goes to the headers, which take a plain value.", id="list in a header"
        ),
        pytest.param(
            Annotated[list[Price], Form()],
            "goes to the form, which takes a plain value or a collection of them.",
            id="list of them in a form",
        ),
    ],
)
def test_a_value_its_part_cant_take_fails(annotation: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.post("/items")
            def create(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_literal_newtype_and_any_values_are_sent_as_text(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            sort: Annotated[Literal["asc", "desc"], Query()],
            order: Annotated[OrderId, Query()],
            price: Annotated[Any, Query()],
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search("asc", OrderId(7), Price())
    assert only_request(sent).url.query.decode() == "sort=asc&order=7&price=9.90+EUR"


@pytest.mark.parametrize(
    ("tags", "query"),
    [
        pytest.param([], "", id="empty list"),
        pytest.param(["a", None, "b"], "tag=a&tag=b", id="None item"),
    ],
)
def test_none_items_and_empty_lists_are_left_out(
    tags: Collection[str | None], query: str, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, tag: Annotated[Collection[str | None], Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(tags)
    request = only_request(sent)
    assert request.url.query.decode() == query
    assert b"?" not in request.url.raw_path or query


# Two values under one key


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        pytest.param(
            Annotated[str, Query(alias="x")],
            Annotated[str, Query(alias="x")],
            "Parameter 'a' and parameter 'b' are both sent as 'x' by Query(), the same key, so one would be lost",
            id="two aliases",
        ),
        pytest.param(
            Annotated[str, Header(alias="B")],
            Annotated[str, Header()],
            "Parameter 'a' and parameter 'b' are sent as 'B' and 'b' by Header(), the same key",
            id="header names ignore case",
        ),
    ],
)
def test_two_values_under_one_key_fail(first: Any, second: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.get("/items")
            def search(self, a: first, b: second) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_one_key_in_two_parts_isnt_a_clash(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, status: Annotated[str, Query()], s: Annotated[str, Header(alias="status")]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search("open", "x")
    request = only_request(sent)
    assert request.url.query.decode() == "status=open"
    assert request.headers["status"] == "x"


# One value or a list of them, and values that can't become text


@pytest.mark.parametrize(
    ("annotation", "value", "query"),
    [
        pytest.param(str | list[str], "a", "tag=a", id="one value"),
        pytest.param(str | list[str], ["a", "b"], "tag=a&tag=b", id="a list of them"),
        pytest.param(Sequence[str], "python", "tag=python", id="a str for a Sequence[str] is one value"),
    ],
)
def test_a_value_or_a_list_of_them_is_decided_at_the_call(
    annotation: Any, value: object, query: str, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, tag: Annotated[annotation, Query()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(value)
    assert only_request(sent).url.query.decode() == query


def test_a_serializer_in_a_parameters_type_fails() -> None:
    epoch = Annotated[datetime.datetime, PlainSerializer(lambda d: int(d.timestamp()), return_type=int)]
    with pytest.raises(DefinitionError, match=re.escape("has a pydantic serializer in its type")):

        class API(ClientX):
            @method.get("/items")
            def search(self, since: Annotated[epoch, Query()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_value_that_cant_become_text_raises_before_sending(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(self, token: Annotated[bytes, Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    with pytest.raises(ArgumentError, match=re.escape("Can't send 'token'")) as caught:
        API(BASE_URL, transport=mock_transport(sent)).search(b"\xff")
    assert caught.value.parameter == "token"
    assert sent == []


DEFAULT_FILTERS = Filters(status="open")


def test_send_exclude_unset_leaves_out_a_parameter_not_passed(mock_transport: MockTransport) -> None:
    # So the server applies its own default; passing the same value sends it.
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            page: Annotated[int, Query(), Send(exclude_unset=True)] = 1,
            filters: Annotated[Filters, Query(), Send(exclude_unset=True)] = DEFAULT_FILTERS,
        ) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.search()
    api.search(1, DEFAULT_FILTERS)
    assert [request.url.query.decode() for request in sent] == ["", "page=1&status=open"]


@pytest.mark.parametrize(
    ("default", "why"),
    [
        pytest.param(inspect.Parameter.empty, "it has no default, so it's always passed", id="no default"),
        pytest.param(None, "its default is None, which is left out anyway", id="None default"),
    ],
)
def test_send_exclude_unset_with_nothing_to_leave_out_fails(default: object, why: str) -> None:
    def search(self: ClientX, page: Annotated[int | None, Query(), Send(exclude_unset=True)]) -> None: ...

    if default is not inspect.Parameter.empty:
        search.__defaults__ = (default,)
    with pytest.raises(DefinitionError, match=re.escape(f"has Send(exclude_unset=...), but {why}")):
        type("API", (ClientX,), {"search": method.get("/items")(search)})
