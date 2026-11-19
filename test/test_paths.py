"""Path templates: placeholders, filled so a value can't change the path."""

import datetime
import enum
import re
import uuid
from collections.abc import Callable
from typing import Annotated, Any

import httpx2
import pytest

from clientx import ArgumentError, AsyncClientX, AsyncResource, ClientX, DefinitionError, Query, Resource, Url, method

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com/v1"


class Color(enum.Enum):
    RED = "red"


def sent_path(sent: list[httpx2.Request]) -> str:
    """Return the one request's path as it went out, percent-encoded."""
    (request,) = sent
    return request.url.raw_path.decode()


def test_each_placeholder_is_filled_with_its_argument(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users/{user_id}/repos/{repo}")
        def repo(self, user_id: int, repo: str) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).repo(7, repo="clientx")
    assert sent_path(sent) == "/v1/users/7/repos/clientx"


def test_a_placeholder_can_appear_twice(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/{lang}/docs/{lang}")
        def docs(self, lang: str) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).docs("en")
    assert sent_path(sent) == "/v1/en/docs/en"


def test_an_empty_path_calls_the_base_url(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get()
        def root(self) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).root()
    assert sent_path(sent) == "/v1/"


@pytest.mark.parametrize(
    ("value", "segment"),
    [
        pytest.param("a b/c?d#e", "a%20b%2Fc%3Fd%23e", id="reserved characters"),
        pytest.param("é", "%C3%A9", id="non-ASCII"),
        pytest.param("100%", "100%25", id="percent sign"),
        pytest.param(".", "%2E", id="dot"),
        pytest.param("..", "%2E%2E", id="dot dot"),
        pytest.param("...", "...", id="three dots"),
        pytest.param(True, "true", id="bool"),
        pytest.param(1.5, "1.5", id="float"),
        pytest.param(Color.RED, "red", id="enum"),
        pytest.param(uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001", id="UUID"),
        pytest.param(datetime.datetime(2026, 11, 17, 9, 30), "2026-11-17T09%3A30%3A00", id="datetime"),
    ],
)
def test_a_value_becomes_one_encoded_segment(value: object, segment: str, mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/items/{item}")
        def item(self, item: Any) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).item(value)
    assert sent_path(sent) == f"/v1/items/{segment}"


@pytest.mark.parametrize(
    ("value", "segments"),
    [
        pytest.param("docs/read me.md", "docs/read%20me.md", id="each segment encoded"),
        pytest.param("a/../b", "a/%2E%2E/b", id="dot dot segment"),
        pytest.param("./x", "%2E/x", id="dot segment"),
    ],
)
def test_a_path_placeholder_keeps_its_slashes(value: str, segments: str, mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/files/{file_path:path}")
        def file(self, file_path: str) -> None: ...

    sent: list[httpx2.Request] = []
    API(BASE_URL, transport=mock_transport(sent)).file(value)
    assert sent_path(sent) == f"/v1/files/{segments}"


def test_doubled_braces_arent_literal_braces() -> None:
    with pytest.raises(DefinitionError, match=re.escape("has a brace that isn't part of a placeholder")):

        class API(ClientX):
            @method.get("/a/{{literal}}/{item}")
            def item(self, item: int) -> None: ...


def test_a_resource_prefix_can_have_placeholders(mock_transport: MockTransport) -> None:
    class Repos(Resource, prefix="/orgs/{org}"):
        @method.get("/repos/{repo}")
        def get(self, org: str, repo: Annotated[str, Url(description="The repository's name")]) -> None: ...

        @method.get("/members")
        def members(self, org: Annotated[str, Url()]) -> None: ...

    class API(ClientX):
        repos = Repos()

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent))
    api.repos.get("acme", "clientx")
    api.repos.members("acme")
    assert [request.url.raw_path.decode() for request in sent] == [
        "/v1/orgs/acme/repos/clientx",
        "/v1/orgs/acme/members",
    ]


@pytest.mark.anyio
async def test_async_endpoints_fill_their_path_too(mock_transport: MockTransport) -> None:
    class Repos(AsyncResource, prefix="/orgs/{org}"):
        @method.get("/repos/{repo}")
        async def get(self, org: str, repo: str) -> None: ...

    class API(AsyncClientX):
        repos = Repos()

    sent: list[httpx2.Request] = []
    await API(BASE_URL, transport=mock_transport(sent)).repos.get("acme", "a b")
    assert sent_path(sent) == "/v1/orgs/acme/repos/a%20b"


@pytest.mark.parametrize(
    ("template", "value", "problem"),
    [
        pytest.param("/users/{name}", None, "None would be sent as 'null'", id="None"),
        pytest.param("/users/{name}", "", "an empty value would remove the segment", id="empty"),
        pytest.param("/files/{name:path}", "/a", "leaves an empty segment", id="leading slash"),
        pytest.param("/files/{name:path}", "a//b", "leaves an empty segment", id="doubled slash"),
        pytest.param("/files/{name:path}", "a/", "leaves an empty segment", id="trailing slash"),
    ],
)
def test_a_value_that_would_change_the_path_raises_before_sending(
    template: str, value: str | None, problem: str, mock_transport: MockTransport
) -> None:
    class API(ClientX):
        @method.get(template)
        def fetch(self, name: Any) -> None: ...

    sent: list[httpx2.Request] = []
    with pytest.raises(ArgumentError, match=re.escape(problem)) as caught:
        API(BASE_URL, transport=mock_transport(sent)).fetch(value)
    assert caught.value.parameter == "name"
    assert "No request was sent" in str(caught.value)
    assert sent == []


@pytest.mark.parametrize(
    ("template", "message"),
    [
        pytest.param("/a/{item:int}", "can't fill the placeholder {item:int}", id="unknown converter"),
        pytest.param("/a/{item:}", None, id="empty converter is accepted"),
        pytest.param("/a/{user-id}", "can't fill the placeholder {user-id}", id="not an identifier"),
        pytest.param("/a/{a.b}", "can't fill the placeholder {a.b}", id="attribute"),
        pytest.param("/a/{c[0]}", "can't fill the placeholder {c[0]}", id="index"),
        pytest.param("/a/{item!r}", "can't fill the placeholder {item!r}", id="conversion"),
        pytest.param("/a/{}", "can't fill the placeholder {}", id="no name"),
        pytest.param("/a/{", "has a brace that isn't part of a placeholder", id="lone opening brace"),
        pytest.param("/a/}", "has a brace that isn't part of a placeholder", id="lone closing brace"),
        pytest.param("/a/{item", "has a brace that isn't part of a placeholder", id="unclosed"),
    ],
)
def test_a_malformed_template_fails_when_the_class_is_defined(template: str, message: str | None) -> None:
    def define() -> None:
        class API(ClientX):
            @method.get(template)
            def fetch(self, item: int) -> None: ...

    if message is None:
        define()
        return
    with pytest.raises(DefinitionError, match=re.escape(message)) as caught:
        define()
    assert "A placeholder is {name}" in str(caught.value)
    assert "Endpoint 'test_a_malformed_template_fails_when_the_class_is_defined.<locals>" in str(caught.value)


def test_a_placeholder_needs_a_parameter() -> None:
    with pytest.raises(DefinitionError, match=re.escape("has the placeholder {user_id}, but no parameter is named")):

        class API(ClientX):
            @method.get("/users/{user_id}")
            def fetch(self, item: int) -> None: ...


def test_the_first_parameter_isnt_a_placeholders_parameter() -> None:
    with pytest.raises(DefinitionError, match=re.escape("has the placeholder {self}, but no parameter is named")):

        class API(ClientX):
            @method.get("/{self}")
            def fetch(self) -> None: ...


def test_a_placeholder_from_a_resource_prefix_needs_a_parameter_too() -> None:
    with pytest.raises(DefinitionError, match=re.escape("Path '/orgs/{org}/members' has the placeholder {org}")):

        class Members(Resource, prefix="/orgs/{org}"):
            @method.get("/members")
            def list(self) -> None: ...


def test_a_url_parameter_needs_a_placeholder() -> None:
    with pytest.raises(DefinitionError, match=re.escape("is marked Url(), but the path '/users' has no placeholder")):

        class API(ClientX):
            @method.get("/users")
            def fetch(self, user_id: Annotated[int, Url()]) -> None: ...


def test_a_placeholders_parameter_cant_go_elsewhere_too() -> None:
    with pytest.raises(DefinitionError, match=re.escape("so it can't also be marked Query()")):

        class API(ClientX):
            @method.get("/users/{user_id}")
            def fetch(self, user_id: Annotated[int, Query()]) -> None: ...


@pytest.mark.parametrize("annotation", [dict[str, str], list[int], int | list[int]], ids=["dict", "list", "union"])
def test_a_placeholders_parameter_must_be_a_plain_value(annotation: object) -> None:
    with pytest.raises(DefinitionError, match=re.escape("so it must be a plain value")):

        class API(ClientX):
            @method.get("/items/{item}")
            def fetch(self, item: annotation) -> None: ...  # type: ignore[valid-type]  # pyright: ignore[reportInvalidTypeForm]


def test_an_endpoint_declared_outside_a_client_class_cant_be_called(mock_transport: MockTransport) -> None:
    @method.get("/loose")
    def loose(self: ClientX) -> None: ...

    class API(ClientX): ...

    with pytest.raises(DefinitionError, match="isn't declared in the body of a ClientX"):
        loose(API(BASE_URL, transport=mock_transport()))
