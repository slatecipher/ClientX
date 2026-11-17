"""Models, dataclasses and mappings with a Query(), Header() or Form() helper, spread into that part."""

import dataclasses
import datetime
import enum
import re
from collections.abc import Callable
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field, field_serializer

from clientx import ClientX, DefinitionError, File, Form, Header, Json, Query, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class Status(enum.Enum):
    OPEN = "open"


class Filters(BaseModel):
    status: Status = Status.OPEN
    page_size: int = Field(default=20, alias="pageSize")
    tags: list[str] = []
    since: datetime.datetime | None = None
    secret: str = Field(default="hidden", exclude=True)
    cursor: str | None = None

    @field_serializer("cursor")
    def _upper(self, value: str | None) -> str | None:
        return value.upper() if value else value


class Tracing(BaseModel):
    x_request_id: str
    trace_parent: str = Field(default="00-abc", alias="traceparent")


@dataclasses.dataclass
class Paging:
    page: int = 1
    per_page: int = 50


class Signup(BaseModel):
    username: str
    remember: bool = False
    scopes: list[str] = []


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


def test_a_models_fields_become_query_parameters(mock_transport: MockTransport) -> None:
    # Dumped first, so the model's own serializers and Field(exclude=True) apply; None fields are left out.
    class API(ClientX):
        @method.get("/issues")
        def search(self, filters: Annotated[Filters, Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(
        Filters(tags=["a", "b"], since=datetime.datetime(2026, 11, 17), cursor="abc")
    )
    assert only_request(sent).url.query.decode() == (
        "status=open&pageSize=20&tags=a&tags=b&since=2026-11-17T00%3A00%3A00&cursor=ABC"
    )


def test_a_dataclasses_fields_become_query_parameters(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/issues")
        def search(self, paging: Annotated[Paging, Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search(Paging(per_page=10))
    assert only_request(sent).url.query.decode() == "page=1&per_page=10"


def test_a_mappings_items_become_query_parameters(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/issues")
        def search(
            self,
            labels: Annotated[dict[str, list[str]], Query()],
            extra: Annotated[dict, Query()] = {},  # noqa: B006 - never mutated
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent), params={"api_key": "k"}).search({"label": ["x", "y"]}, extra={"n": 1})
    assert only_request(sent).url.query.decode() == "api_key=k&label=x&label=y&n=1"


def test_a_models_fields_become_headers(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/traced")
        def traced(
            self,
            tracing: Annotated[Tracing, Header()],
            more: Annotated[dict[str, str], Header()] = {},  # noqa: B006 - never mutated
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).traced(
        Tracing(x_request_id="r-1"), more={"X-Custom_Name": "as given"}
    )
    request = only_request(sent)
    # A field's name gets hyphens and an alias is kept; a mapping's keys are sent as they are.
    assert [(name.decode(), value.decode()) for name, value in request.headers.raw][-3:] == [
        ("x-request-id", "r-1"),
        ("traceparent", "00-abc"),
        ("X-Custom_Name", "as given"),
    ]


def test_a_models_fields_become_form_fields(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/signup")
        def signup(self, form: Annotated[Signup, Form()], avatar: Annotated[Any, File()] = None) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.signup(Signup(username="ada", remember=True, scopes=["read", "write"]))
    api.signup(Signup(username="ada"), avatar=("a.png", b"\x89PNG", "image/png"))
    form, multipart = sent
    assert form.content == b"username=ada&remember=true&scopes=read&scopes=write"
    assert multipart.headers["content-type"].startswith("multipart/form-data")
    assert b'name="username"\r\n\r\nada' in multipart.read()


def test_the_later_parameter_wins_when_keys_clash(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/clash")
        def clash(self, a: Annotated[dict[str, str], Query()], b: Annotated[dict[str, str], Query()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).clash({"k": "from a", "only_a": "1"}, {"k": "from b"})
    assert only_request(sent).url.query.decode() == "k=from+b&only_a=1"


def test_an_optional_model_thats_none_sends_nothing(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/issues")
        def search(self, filters: Annotated[Filters | None, Query()] = None) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).search()
    assert only_request(sent).url.query.decode() == ""


class Inner(BaseModel):
    a: int


class Nested(BaseModel):
    inner: Inner


class WithList(BaseModel):
    tags: list[str]


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        pytest.param(
            Annotated[Nested, Query()],
            "sends each field of Nested to the query string, which takes a plain value, such as str or int, "
            "or a list of them; field 'inner' isn't one",
            id="query field that's a model",
        ),
        pytest.param(
            Annotated[WithList, Header()],
            "sends each field of WithList to the headers, which take a plain value, such as str or int; "
            "field 'tags' isn't one",
            id="header field that's a list",
        ),
        pytest.param(
            Annotated[dict[str, list[str]], Header()],
            "sends each item of the mapping to the headers, which take a plain value, such as str or int; "
            "its value type isn't one",
            id="header mapping of lists",
        ),
    ],
)
def test_each_spread_field_must_fit_its_part(annotation: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.post("/items")
            def create(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_form_field_can_be_a_list(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, form: Annotated[WithList, Form()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(WithList(tags=["a", "b"]))
    assert only_request(sent).content == b"tags=a&tags=b"


class HelperInAnnotated(BaseModel):
    q: Annotated[int, Query()]


class HelperAsDefault(BaseModel):
    q: int = Query(1)


@pytest.mark.parametrize(
    "annotation",
    [Annotated[HelperInAnnotated, Query()], HelperInAnnotated, Annotated[HelperAsDefault, Json()]],
    ids=["spread into the query", "JSON body", "helper as the field's default"],
)
def test_a_helper_on_a_models_field_fails(annotation: Any) -> None:
    with pytest.raises(
        DefinitionError, match=re.escape("has a clientx.arguments helper, but ClientX reads helpers only")
    ):

        class API(ClientX):
            @method.post("/items")
            def create(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]
