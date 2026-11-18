"""Request bodies: JSON, raw content, forms, files, and the one-body rule."""

import datetime
import json
import re
from collections.abc import Callable
from typing import Annotated, Any

import httpx2
import pytest
from pydantic import BaseModel, Field, RootModel

from clientx import AsyncClientX, Body, ClientX, DefinitionError, File, Form, Json, Query, Send, method

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


def test_a_json_field_thats_none_is_left_out(mock_transport: MockTransport) -> None:
    # So a PATCH sends only what was passed, and nothing at all when nothing
    # was.
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
    api.update(7)
    with_name, empty = sent
    assert json.loads(with_name.content) == {"name": "Ada"}
    assert (empty.content, content_type(empty)) == (b"", "")


def test_a_lone_body_thats_none_sends_no_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser | None, Json()] = None) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).create()
    assert only_request(sent).content == b""


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
        pytest.param(Embedded[list[str]], ["a"], {"ids": ["a"]}, id="type alias"),
        pytest.param(Annotated[str, Json(), Send(embed=True)], "a", {"ids": "a"}, id="plain value, keyed anyway"),
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


def test_without_send_embed_a_lone_list_is_the_whole_body(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/devices/actions")
        def act(self, ids: Annotated[list[str], Json()]) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).act(["a", "b"])
    assert json.loads(only_request(sent).content) == ["a", "b"]


@pytest.mark.parametrize(
    ("path", "annotation", "message"),
    [
        pytest.param(
            "/items",
            Annotated[int, Query(), Send(embed=True)],
            "has Send(embed=...), which sends a JSON body parameter under its name, but it goes to the request's "
            "params",
            id="query parameter",
        ),
        pytest.param(
            "/items",
            Annotated[int, Query(), Send(embed=False)],
            "has Send(embed=...)",
            id="embed=False counts too",
        ),
        pytest.param(
            "/items",
            Annotated[bytes, Body(), Send(embed=True)],
            "but it goes to the request's content",
            id="raw content",
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


def test_a_form_field_must_be_a_plain_value_or_a_list_of_them() -> None:
    with pytest.raises(DefinitionError, match=re.escape("goes to the form, which takes a plain value")):

        class API(ClientX):
            @method.post("/items")
            def create(self, users: Annotated[list[NewUser], Form()]) -> None: ...


# One kind of body


@pytest.mark.parametrize(
    ("first", "second", "kinds"),
    [
        pytest.param(
            Annotated[dict[str, str], Json()],
            Annotated[bytes, Body()],
            "(JSON), 'p2' (raw content)",
            id="JSON and raw content",
        ),
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
