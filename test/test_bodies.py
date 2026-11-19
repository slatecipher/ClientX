"""Request bodies: JSON, raw content, forms, files, and the one-body rule."""

import dataclasses
import datetime
import io
import json
import pathlib
import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field, RootModel
from pydantic.dataclasses import dataclass as pydantic_dataclass

from clientx import ArgumentError, AsyncClientX, Body, ClientX, DefinitionError, File, Form, Json, Query, Send, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class NewUser(BaseModel):
    name: str
    email_address: str = Field(alias="emailAddress")
    joined: datetime.datetime | None = None


class Admin(NewUser):
    level: int = 1


class Tags(RootModel[list[str]]):
    pass


class Flagged(BaseModel):
    ids: Annotated[list[str], Send(embed=True)]


type Embedded[T] = Annotated[T, Json(), Send(embed=True)]


def only_request(sent: list[httpx2.Request]) -> httpx2.Request:
    (request,) = sent
    return request


def content_type(request: httpx2.Request) -> str:
    return request.headers.get("content-type", "").split(";")[0]


# JSON


def test_a_lone_model_is_the_whole_json_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(
        NewUser(name="Ada", emailAddress="ada@example.com", joined=datetime.datetime(2026, 11, 17))
    )
    request = only_request(sent)
    assert content_type(request) == "application/json"
    assert json.loads(request.content) == {
        "name": "Ada",
        "emailAddress": "ada@example.com",
        "joined": "2026-11-17T00:00:00",
    }


def test_a_model_is_sent_by_its_own_type(mock_transport: MockTransport) -> None:
    # A subclass keeps its extra fields, and a field the caller didn't set is
    # sent with its default.
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(Admin(name="Root", emailAddress="r@example.com", level=9))
    assert json.loads(only_request(sent).content) == {
        "name": "Root",
        "emailAddress": "r@example.com",
        "joined": None,
        "level": 9,
    }


@pytest.mark.parametrize(
    ("annotation", "value", "body"),
    [
        pytest.param(
            list[NewUser],
            [NewUser(name="A", emailAddress="a@x")],
            [{"name": "A", "emailAddress": "a@x", "joined": None}],
            id="list of models",
        ),
        pytest.param(Tags, Tags(["a", "b"]), ["a", "b"], id="RootModel"),
        pytest.param(dict[str, Any], {"keep": None, "n": 1}, {"keep": None, "n": 1}, id="dict with a None"),
        pytest.param(Any, {"n": 1}, {"n": 1}, id="Any"),
    ],
)
def test_a_lone_list_mapping_or_root_model_is_the_whole_json_body(
    annotation: Any, value: object, body: object, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, items: Annotated[annotation, Json()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(value)
    assert json.loads(only_request(sent).content) == body


def test_a_lone_plain_json_value_is_sent_under_its_name(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.patch("/posts/{post_id}")
        def rename(self, post_id: int, title: Annotated[str, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).rename(1, "New")
    assert json.loads(only_request(sent).content) == {"title": "New"}


def test_several_json_parameters_are_keyed_by_name(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/invites")
        def invite(self, user: Annotated[NewUser, Json()], notify: Annotated[bool, Json()] = True) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).invite(NewUser(name="Ada", emailAddress="a@x"))
    assert json.loads(only_request(sent).content) == {
        "user": {"name": "Ada", "emailAddress": "a@x", "joined": None},
        "notify": True,
    }


def test_a_json_field_is_sent_under_its_alias(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.patch("/users/{user_id}")
        def update(self, user_id: int, email: Annotated[str, Json(alias="emailAddress")]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).update(7, "e@x")
    assert json.loads(only_request(sent).content) == {"emailAddress": "e@x"}


def test_a_json_field_not_passed_is_left_out_and_one_passed_as_none_is_null(
    mock_transport: MockTransport,
) -> None:
    # So a PATCH sends only what was passed, null to clear a field, and nothing
    # at all when nothing was.
    class API(ClientX):
        @method.patch("/users/{user_id}")
        def update(
            self,
            user_id: int,
            name: Annotated[str | None, Json()] = None,
            tags: Annotated[list[str] | None, Json()] = None,
        ) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.update(7, name="Ada")
    api.update(7, name=None)
    api.update(7)
    with_name, with_null, empty = sent
    assert json.loads(with_name.content) == {"name": "Ada"}
    assert json.loads(with_null.content) == {"name": None}
    assert (empty.content, content_type(empty)) == (b"", "")


def test_a_lone_body_thats_none_sends_no_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser | None, Json()] = None) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(None)
    request = only_request(sent)
    assert (request.content, content_type(request)) == (b"", "")


@pytest.mark.anyio
async def test_async_endpoints_send_bodies_too(mock_transport: MockTransport) -> None:
    class API(AsyncClientX):
        @method.post("/users")
        async def create(self, user: Annotated[NewUser, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    await API(BASE_URL, transport=mock_transport(sent)).create(NewUser(name="Ada", emailAddress="a@x"))
    assert json.loads(only_request(sent).content)["emailAddress"] == "a@x"


# Send(embed=True): a lone JSON parameter sent under its name (#129)


@pytest.mark.parametrize(
    ("annotation", "value", "body"),
    [
        pytest.param(Annotated[list[str], Json(), Send(embed=True)], ["a", "b"], {"ids": ["a", "b"]}, id="list"),
        pytest.param(
            Annotated[list[str], Json(alias="deviceIds"), Send(embed=True)], ["a"], {"deviceIds": ["a"]}, id="alias"
        ),
        pytest.param(
            Annotated[NewUser, Json(), Send(embed=True)],
            NewUser(name="Ada", emailAddress="a@x"),
            {"ids": {"name": "Ada", "emailAddress": "a@x", "joined": None}},
            id="model",
        ),
    ],
)
def test_send_embed_sends_a_lone_json_parameter_under_its_name(
    annotation: Any, value: object, body: object, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.post("/devices/actions")
        def act(self, action_name: Annotated[str, Query()], ids: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).act("contain", value)
    request = only_request(sent)
    assert (request.url.query.decode(), json.loads(request.content)) == ("action_name=contain", body)


def test_the_parameters_send_replaces_an_aliass(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/devices/actions")
        def act(self, ids: Annotated[Embedded[list[str]], Send(embed=False)]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).act(["a", "b"])
    assert json.loads(only_request(sent).content) == ["a", "b"]


@pytest.mark.parametrize(
    ("path", "annotation", "message"),
    [
        pytest.param(
            "/items",
            Annotated[int, Query(), Send(embed=True)],
            "has Send(embed=...), which applies only to a Json() parameter, but it's marked Query()",
            id="query parameter",
        ),
        pytest.param(
            "/items",
            Annotated[int, Query(), Send(embed=False)],
            "has Send(embed=...)",
            id="embed=False counts too",
        ),
        pytest.param(
            "/items/{p}",
            Annotated[int, Send(embed=True)],
            "so Send doesn't apply to it",
            id="path parameter",
        ),
        pytest.param(
            "/items",
            Annotated[list[str], Send(embed=True)] | None,  # pyright: ignore[reportOperatorIssue]
            "has a Send inside its type",
            id="nested",
        ),
        pytest.param(
            "/items",
            Flagged,
            "Field 'ids' of Flagged has a Send, but ClientX reads Send only on endpoint parameters",
            id="on a model's field",
        ),
    ],
)
def test_send_where_it_cant_apply_fails(path: str, annotation: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.post(path)
            def act(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


# Raw content


@pytest.mark.parametrize("value", [b"\x00\x01raw", "text body"], ids=["bytes", "str"])
def test_body_sends_raw_content(value: bytes | str, mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.put("/blobs/{name}")
        def upload(self, name: str, data: Annotated[bytes | str, Body()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).upload("b", value)
    expected = value.encode() if isinstance(value, str) else value
    assert only_request(sent).content == expected


# Forms and files


def test_form_fields_are_sent_url_encoded(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/login")
        def login(
            self,
            username: Annotated[str, Form()],
            remember: Annotated[bool, Form()] = False,
            scopes: Annotated[list[str] | None, Form()] = None,
            nickname: Annotated[str | None, Form(alias="nickName")] = None,
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).login("ada", remember=True, scopes=["read", "write"])
    request = only_request(sent)
    assert content_type(request) == "application/x-www-form-urlencoded"
    assert request.content == b"username=ada&remember=true&scopes=read&scopes=write"


def test_files_with_form_fields_are_sent_as_multipart(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/upload")
        def upload(self, file: Annotated[Any, File(alias="attachment")], title: Annotated[str, Form()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).upload(("a.txt", b"hello", "text/plain"), title="T")
    request = only_request(sent)
    body = request.read()
    assert content_type(request) == "multipart/form-data"
    assert b'name="title"\r\n\r\nT' in body
    assert b'name="attachment"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\nhello' in body


# One kind of body


@pytest.mark.parametrize(
    ("first", "second", "kinds"),
    [
        pytest.param(Annotated[NewUser, Json()], Annotated[str, Form()], "(JSON), 'p2' (a form)", id="JSON and a form"),
        pytest.param(
            Annotated[bytes, Body()],
            Annotated[bytes, File()],
            "(raw content), 'p2' (a form)",
            id="raw content and a file",
        ),
    ],
)
def test_an_endpoint_sends_one_kind_of_body(first: Any, second: Any, kinds: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(f"more than one kind of body: 'p1' {kinds}")):

        class API(ClientX):
            @method.post("/items")
            def create(self, p1: first, p2: second) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_an_endpoint_has_at_most_one_raw_body() -> None:
    with pytest.raises(DefinitionError, match=re.escape("Parameters 'a', 'b' are all marked Body()")):

        class API(ClientX):
            @method.post("/items")
            def create(self, a: Annotated[bytes, Body()], b: Annotated[str, Body()]) -> None: ...


def test_query_parameters_go_with_any_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser, Json()], dry_run: Annotated[bool, Query()] = False) -> None: ...

        @method.post("/upload")
        def upload(
            self, file: Annotated[bytes, File()], title: Annotated[str, Form()], page: Annotated[int, Query()] = 1
        ) -> None: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.create(NewUser(name="Ada", emailAddress="a@x"), dry_run=True)
    api.upload(b"x", title="T")
    assert [(request.url.query.decode(), content_type(request)) for request in sent] == [
        ("dry_run=true", "application/json"),
        ("page=1", "multipart/form-data"),
    ]


# JSON: null, and Send's dump options


class Profile(BaseModel):
    name: str = "sam"
    nickname: str | None = None


@pydantic_dataclass
class Window:
    start: int = 0
    end: int | None = None


@dataclasses.dataclass
class StdWindow:
    start: int = 0
    end: int | None = None


class Opaque:
    pass


@pytest.mark.parametrize(
    ("annotation", "value", "body"),
    [
        pytest.param(
            Annotated[Profile, Json(), Send(exclude_defaults=True)],
            Profile(name="sam", nickname="s"),
            {"nickname": "s"},
            id="exclude_defaults",
        ),
        pytest.param(
            Annotated[list[Profile], Json(), Send(exclude_unset=True)],
            [Profile(name="ana")],
            [{"name": "ana"}],
            id="nested in a list",
        ),
        pytest.param(
            Annotated[Window, Json(), Send(exclude_none=True)], Window(start=3), {"start": 3}, id="pydantic dataclass"
        ),
    ],
)
def test_send_dump_options_shape_the_json(
    annotation: Any, value: object, body: object, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create(value)
    assert json.loads(only_request(sent).content) == body


def test_exclude_none_on_a_json_field_leaves_out_an_explicit_none(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.patch("/me")
        def update(
            self,
            profile: Annotated[Profile | None, Json(), Send(exclude_none=True)] = None,
            bio: Annotated[str | None, Json()] = None,
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).update(profile=None, bio="x")
    assert json.loads(only_request(sent).content) == {"bio": "x"}


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        pytest.param(
            Annotated[StdWindow, Json(), Send(exclude_none=True)],
            "leaves out fields of a pydantic model or pydantic dataclass (pydantic doesn't apply it to a stdlib "
            "dataclass",
            id="stdlib dataclass",
        ),
        pytest.param(Annotated[str, Json(), Send(exclude_defaults=True)], "but its type has none", id="plain value"),
        pytest.param(
            Annotated[str, Json(), Send(exclude_unset=True)],
            "has Send(exclude_unset=...), but it has no default, so it's always passed",
            id="exclude_unset with nothing to leave out",
        ),
    ],
)
def test_a_dump_option_where_it_cant_apply_fails(annotation: Any, message: str) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.post("/items")
            def create(self, p: annotation) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_json_value_pydantic_cant_serialize_raises_before_sending(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/items")
        def create(self, price: Annotated[Any, Json()], note: Annotated[str, Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    with pytest.raises(
        ArgumentError, match=re.escape("Can't send 'price' as JSON: Unable to serialize unknown type")
    ) as caught:
        API(BASE_URL, transport=mock_transport(sent)).create(Opaque(), "x")
    assert caught.value.parameter == "price"
    assert sent == []


# Files: what a file can be


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param(str, id="str"),
        pytest.param(pathlib.Path, id="Path"),
    ],
)
def test_a_file_that_isnt_bytes_a_binary_file_or_a_file_tuple_fails(annotation: Any) -> None:
    message = (
        'A file is bytes, a binary file such as open(path, "rb"), or a (filename, content[, content_type[, '
        "headers]]) tuple, or Any"
    )
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.post("/upload")
            def upload(self, doc: Annotated[annotation, File()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


@pytest.mark.parametrize(
    ("annotation", "value", "filename"),
    [
        pytest.param(io.BytesIO, io.BytesIO(b"%PDF"), "upload", id="BytesIO"),
        pytest.param(
            tuple[str, bytes, str, dict[str, str]],
            ("a.pdf", b"%PDF", "application/pdf", {"X-Checksum": "abc"}),
            "a.pdf",
            id="with headers",
        ),
    ],
)
def test_file_values_that_fit_are_sent(
    annotation: Any, value: object, filename: str, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.post("/upload")
        def upload(self, doc: Annotated[annotation, File()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).upload(value)
    assert f'filename="{filename}"' in only_request(sent).read().decode()


def test_a_list_of_files_repeats_the_field(mock_transport: MockTransport) -> None:
    # A None in the list is left out, and another File() can share the field.
    class API(ClientX):
        @method.post("/upload")
        def upload(
            self,
            docs: Annotated[list[tuple[str, bytes] | None], File()],
            extra: Annotated[tuple[str, bytes], File(alias="docs")],
        ) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).upload([("a.pdf", b"A"), None], ("b.pdf", b"B"))
    body = only_request(sent).read().decode()
    assert body.count('name="docs"') == 2
    assert 'filename="a.pdf"' in body
    assert 'filename="b.pdf"' in body


# Raw content: what a raw body can be


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param(NewUser, id="model"),
        pytest.param(Iterator[str], id="stream of text"),
    ],
)
def test_a_raw_body_that_isnt_text_bytes_or_a_stream_fails(annotation: Any) -> None:
    message = "The raw body is str, bytes, or an iterable or async iterable of bytes, or Any."
    with pytest.raises(DefinitionError, match=re.escape(message)):

        class API(ClientX):
            @method.put("/blobs")
            def upload(self, data: Annotated[annotation, Body()]) -> None: ...  # pyright: ignore[reportInvalidTypeForm]


def test_a_sync_client_streams_an_iterable_of_bytes(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.put("/blobs")
        def upload(self, data: Annotated[Iterator[bytes], Body()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).upload(iter([b"a", b"b"]))
    assert only_request(sent).read() == b"ab"


def test_an_async_stream_on_a_sync_client_fails() -> None:
    with pytest.raises(DefinitionError, match=re.escape("with an async iterable, but the endpoint is sync")):

        class API(ClientX):
            @method.put("/blobs")
            def upload(self, data: Annotated[AsyncIterator[bytes], Body()]) -> None: ...


def test_a_sync_stream_on_an_async_client_fails() -> None:
    # A list of bytes too: httpx2's AsyncClient streams only async iterables.
    with pytest.raises(DefinitionError, match=re.escape("with a sync iterable, but the endpoint is async")):

        class API(AsyncClientX):
            @method.put("/blobs")
            async def upload(self, data: Annotated[list[bytes], Body()]) -> None: ...


@pytest.mark.anyio
async def test_an_async_client_streams_an_async_iterable(mock_transport: MockTransport) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    class API(AsyncClientX):
        @method.put("/blobs")
        async def upload(self, data: Annotated[AsyncIterator[bytes], Body()]) -> None: ...

    sent: list[httpx2.Request] = []
    await API(BASE_URL, transport=mock_transport(sent)).upload(chunks())
    assert only_request(sent).content == b"ab"
