"""Query parameters and headers: where a parameter goes, the name it's sent under, and how its value is sent."""

import datetime
import enum
import json
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal, Optional

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import ClientX, DefinitionError, Header, Query, Url, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class Color(enum.Enum):
    RED = "red"


class Filters(BaseModel):
    status: str


type HeaderValue = Annotated[str, Header()]
type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


def header_names(request: httpx2.Request) -> list[str]:
    """Return the request's header names as they were sent, in their own case."""
    return [name.decode() for name, _ in request.headers.raw]


# Where a parameter goes


def test_a_plain_parameter_without_a_helper_goes_to_the_query(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items")
        def search(
            self,
            page: int = 1,
            flag: bool = False,
            color: Color = Color.RED,
            since: datetime.datetime | None = None,
            kind: Literal["a", "b"] = "a",
            raw=None,  # Unannotated on purpose: it goes to the query too.
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(
        page=2, flag=True, since=datetime.datetime(2026, 11, 17, 9, 30), kind="b", raw="r"
    )
    assert only_request(sent).url.query.decode() == (
        "page=2&flag=true&color=red&since=2026-11-17T09%3A30%3A00&kind=b&raw=r"
    )


def test_defaults_are_sent_and_none_is_left_out(mock_transport: MockTransport) -> None:
    # Defaults are sent, as a Python call would use them (#135); `None` lets the server decide.
    class API(ClientX):
        @method.get("/items")
        def search(self, page: int = 1, q: str | None = None, opt: Optional[int] = None) -> None: ...  # noqa: UP045

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search()
    assert only_request(sent).url.query.decode() == "page=1"


def test_a_collection_without_a_helper_goes_to_json_not_the_query(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, tags: list[str], keep: int = 1) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(["a"])
    request = only_request(sent)
    assert request.url.query.decode() == "keep=1"
    assert json.loads(request.content) == ["a"]


def test_a_recursive_type_alias_is_inferred_as_json(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/values")
        def store(self, value: JsonValue) -> None: ...

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
        def search(self, page: int) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent), params={"api_key": "k"}).search(2)
    assert only_request(sent).url.query.decode() == "api_key=k&page=2"


@pytest.mark.parametrize(
    "annotation",
    [Annotated[list[Filters], Query()], Annotated[int | list[int], Query()]],
    ids=["list of models", "value or list"],
)
def test_a_query_parameter_must_be_a_plain_value_or_a_list_of_them(annotation: Any) -> None:
    with pytest.raises(DefinitionError, match=re.escape("goes to the query string, which takes a plain value")):

        class API(ClientX):
            @method.get("/items")
            def search(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


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


def test_a_header_must_be_a_plain_value() -> None:
    with pytest.raises(DefinitionError, match=re.escape("goes to the headers, which take a plain value")):

        class API(ClientX):
            @method.get("/items")
            def search(self, tags: Annotated[list[str], Header()]) -> None: ...


# Where a helper can be


@pytest.mark.parametrize(
    "annotation",
    [
        # Python supports `|` on Annotated; pyright doesn't model it outside an annotation.
        Annotated[str, Header()] | None,  # pyright: ignore[reportOperatorIssue]
        Optional[Annotated[int, Header()]],  # noqa: UP045
        list[Annotated[int, Query()]],
        HeaderValue | None,
    ],
    ids=["union", "Optional", "list item", "type alias in a union"],
)
def test_a_helper_inside_a_parameters_type_fails(annotation: Any) -> None:
    with pytest.raises(DefinitionError, match=re.escape("has a helper inside its type")):

        class API(ClientX):
            @method.get("/items")
            def search(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_plain_field_inside_a_type_isnt_a_helper(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, counts: list[Annotated[int, Field(gt=0)]]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create([1, 2])
    assert json.loads(only_request(sent).content) == [1, 2]


@pytest.mark.parametrize(
    ("path", "annotation"),
    [
        ("/items", Annotated[int, Query(default=1)]),
        ("/items", Annotated[str, Header(default_factory=str)]),
        ("/items/{p}", Annotated[int, Url(None)]),
    ],
    ids=["Query(default=)", "Header(default_factory=)", "Url(default)"],
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
