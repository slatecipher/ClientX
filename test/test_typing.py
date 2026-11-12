# pyright: reportUnnecessaryTypeIgnoreComment=true, reportUntypedFunctionDecorator=true
# mypy: disable-error-code="empty-body"
"""Static typing contract for decorated endpoints and decoders.

Pyright and mypy both check this file in the blocking ``make typecheck`` step, so CI
fails if the typing contract regresses for users of either checker:

- ``assert_type`` fails if the inferred type is not exactly the expected one.
- Each line that must be rejected has one comment per checker: ``# type: ignore[code]``
  for mypy, then ``# pyright: ignore[rule]``. Pyright doesn't read mypy's comments
  (``enableTypeIgnoreComments = false`` in ``pyproject.toml``), so each checker reports
  its own comment if it's unused: pyright through the file-level
  ``reportUnnecessaryTypeIgnoreComment``, mypy through ``warn_unused_ignores`` in its
  ``strict`` mode. Code that should be rejected but is accepted is reported.
- ``reportUntypedFunctionDecorator`` is enabled because pyright otherwise hides an
  untyped decorator by falling back to the undecorated signature. mypy has no such
  fallback and would see every endpoint as ``Any``; its ``strict`` mode reports an
  untyped decorator too.
- mypy's ``empty-body`` check is off, as the README tells mypy users to do, because
  endpoint bodies are ``...``.

The tests also run under pytest against a mock transport.
"""

from collections.abc import Iterator
from typing import Annotated, Any, assert_type

import httpx2
import pytest
from pydantic import BaseModel, TypeAdapter

from clientx import Body, ClientX, Header, PathParam, Query, Resource, Response
from clientx.decoders import (
    ModelDecoder,
    StreamLinesDecoder,
    StreamResponseDecoder,
    TypeAdapterDecoder,
    json_decoder,
    text_decoder,
)
from clientx.exceptions import MissingDecoderError
from clientx.methods import delete, get, post


class User(BaseModel):
    name: str


class ItemsClient(ClientX):
    @get("/items/{item_id}")
    def get_item(self, item_id: str) -> Response: ...

    @post("/items", decoder=json_decoder)
    def create_item(self, json: dict[str, object]) -> Any: ...

    @delete("/items/{item_id}")
    def delete_item(self, item_id: str) -> None: ...


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: str) -> User: ...

    @get("/users", decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def list_users(self) -> list[User]: ...

    @get("/users/{user_id}/bio", decoder=text_decoder)
    def get_bio(self, user_id: str) -> str: ...

    @get("/users/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]: ...

    @get("/users/export", decoder=StreamResponseDecoder())
    def export(self) -> Response: ...

    # The decoder produces a User, so declaring a str return is rejected.
    @get("/users/{user_id}/name", decoder=ModelDecoder(User))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    def get_user_name(self, user_id: str) -> str: ...


class UsersResource(Resource, prefix="/users"):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: str) -> User: ...

    @post("")
    def create(self, json: dict[str, object]) -> Response: ...


class GroupsResource(Resource, prefix="/groups"):
    members = UsersResource()


class ResourcesClient(ClientX):
    users = UsersResource()
    groups = GroupsResource()


class SearchClient(ClientX):
    @get("/users", decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def search(
        self,
        name: Annotated[str | None, Query("q")] = None,
        authorization: Annotated[str | None, Header("Authorization")] = None,
    ) -> list[User]: ...

    @post("/users")
    def create(self, user: Annotated[User, Body()]) -> Response: ...


class StatusClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User), raise_for_status=False)
    def lookup(self, user_id: str) -> User: ...

    @delete("/users/{user_id}", raise_for_status=True)
    def remove(self, user_id: str) -> None: ...


class ValidatingClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User), validate_arguments=True)
    def lookup(self, user_id: str) -> User: ...

    @delete("/users/{user_id}", validate_arguments=False, raise_for_status=False)
    def remove(self, user_id: str) -> None: ...


def _transport() -> httpx2.MockTransport:
    payloads: dict[str, object] = {
        "/users/1": {"name": "Ada"},
        "/users": [{"name": "Ada"}],
    }
    return httpx2.MockTransport(lambda request: httpx2.Response(200, json=payloads.get(request.url.path, {"ok": True})))


def test_decorated_methods_keep_their_declared_types() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    assert_type(client.get_item("1"), Response)
    assert_type(client.get_item(item_id="1"), Response)
    assert_type(client.create_item({"name": "x"}), Any)
    assert_type(client.delete_item("1"), None)


def test_decorated_methods_reject_wrong_arguments() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    client.get_item(1)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    client.create_item(json="not a dict")  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        client.delete_item()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_resources_are_typed_attributes_and_keep_endpoint_signatures() -> None:
    client = ResourcesClient("https://example.test", transport=_transport())

    assert_type(client.users, UsersResource)
    assert_type(ResourcesClient.users, UsersResource)
    assert_type(client.groups.members, UsersResource)
    assert_type(client.users.retrieve("1"), User)
    assert_type(client.users.create({"name": "x"}), Response)
    client.users.retrieve(1)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        client.users.create()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_decoded_methods_return_the_decoder_output_type() -> None:
    client = UsersClient("https://example.test", transport=_transport())

    assert_type(client.get_user("1"), User)
    assert_type(client.list_users(), list[User])
    assert_type(client.get_bio("1"), str)
    assert_type(client.events(), Iterator[str])
    response = client.export()
    assert_type(response, Response)
    response.close()


def test_decoders_called_directly_return_the_decoded_type() -> None:
    response = httpx2.Response(200, json=[{"name": "Ada"}])

    assert_type(ModelDecoder(User)(httpx2.Response(200, json={"name": "Ada"})), User)
    assert_type(TypeAdapterDecoder(TypeAdapter(list[User]))(response), list[User])


def test_a_with_block_cant_swallow_an_error() -> None:
    """``ClientX.__exit__`` returns ``None``, so a ``with`` block can't swallow an exception.

    If it returned ``bool``, type checkers would report ``first_user_agent`` as missing a
    return statement, since the block could exit without returning.
    """

    def first_user_agent() -> str:
        with ClientX("https://example.test") as client:
            return client.user_agent

    assert first_user_agent().startswith("ClientX/")


def test_methods_without_decoder_must_return_response_or_none() -> None:
    with pytest.raises(MissingDecoderError):

        class Broken(ClientX):
            @get("/users/{user_id}")  # type: ignore[type-var]  # pyright: ignore[reportArgumentType]
            def get_user(self, user_id: str) -> User: ...


def test_stream_is_decided_by_the_decoder_not_a_flag() -> None:
    with pytest.raises(TypeError):

        class Broken(ClientX):
            @get("/users/{user_id}", decoder=ModelDecoder(User), stream=True)  # type: ignore[call-overload, untyped-decorator]  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
            def get_user(self, user_id: str) -> User: ...


def test_event_hooks_accept_hooks_typed_for_what_they_receive() -> None:
    """Request hooks get an httpx2.Request and response hooks an httpx2.Response."""
    seen: list[str] = []

    def on_request(request: httpx2.Request) -> None:
        seen.append(f"request {request.url.path}")

    def on_response(response: httpx2.Response) -> None:
        seen.append(f"response {response.status_code}")

    class UsersClient(ClientX):
        @get("/users")
        def list_users(self) -> Response: ...

    client = UsersClient(
        "https://example.test",
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200)),
        event_hooks={"request": [on_request], "response": [on_response]},
    )
    client.list_users()

    assert seen == ["request /users", "response 200"]


def _construct_with_every_httpx2_option() -> ClientX:
    """Static check only (never called): every httpx2.Client option type-checks, typos don't.

    Not run under pytest because a real ``cert`` would be loaded from disk.
    """
    ClientX("https://example.test", timout=5.0)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
    return ClientX(
        "https://example.test",
        auth=("user", "secret"),
        params={"q": "1"},
        headers={"X-Env": "dev"},
        cookies={"session": "abc"},
        verify=True,
        cert=("client.pem", "client.key"),
        trust_env=False,
        http1=True,
        http2=False,
        proxy=None,
        mounts={"https://internal.test": httpx2.HTTPTransport()},
        timeout=5.0,
        follow_redirects=True,
        limits=httpx2.Limits(max_connections=10),
        max_redirects=5,
        event_hooks={"request": []},
        transport=httpx2.HTTPTransport(),
        default_encoding="utf-8",
    )


def test_client_options_accept_every_form_httpx2_accepts() -> None:
    """Each httpx2.Client option takes the forms httpx2 itself takes, not just one of them."""

    def sign(request: httpx2.Request) -> httpx2.Request:
        return request

    def no_encoding(content: bytes) -> str | None:
        return None

    clients = [
        ClientX("https://example.test", params={"page": 1, "tags": ["a", "b"], "q": None}),
        ClientX("https://example.test", params=[("page", 1)]),
        ClientX("https://example.test", params="page=1"),
        ClientX("https://example.test", headers=httpx2.Headers({"X-Env": "dev"})),
        ClientX("https://example.test", headers=[("X-Env", "dev")]),
        ClientX("https://example.test", auth=sign),
        ClientX("https://example.test", auth=("user", b"secret")),
        ClientX("https://example.test", timeout=(1.0, 5.0, 5.0, None)),
        ClientX("https://example.test", timeout=None),
        ClientX("https://example.test", transport=None),
        ClientX("https://example.test", default_encoding=no_encoding),
    ]

    assert all(isinstance(client.client, httpx2.Client) for client in clients)


def test_raise_for_status_options_keep_endpoint_signatures() -> None:
    client = StatusClient("https://example.test", raise_for_status=False, transport=_transport())

    assert_type(client.lookup("1"), User)
    assert_type(client.remove("1"), None)
    StatusClient("https://example.test", raise_for_status="no")  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    get("/users", raise_for_status="no")  # type: ignore[call-overload]  # pyright: ignore[reportArgumentType]


def test_validate_arguments_options_keep_endpoint_signatures() -> None:
    client = ValidatingClient("https://example.test", validate_arguments=True, transport=_transport())

    assert_type(client.lookup("1"), User)
    assert_type(client.remove("1"), None)
    ValidatingClient("https://example.test", validate_arguments="yes")  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    get("/users", validate_arguments="yes")  # type: ignore[call-overload]  # pyright: ignore[reportArgumentType]


def test_request_part_helpers_keep_endpoint_signatures() -> None:
    client = SearchClient("https://example.test", transport=_transport())

    assert_type(client.search(name="Ada", authorization="Bearer t"), list[User])
    assert_type(client.create(User(name="Ada")), Response)
    client.search(name=1)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    client.create({"name": "Ada"})  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


def test_helper_descriptions_are_keyword_only() -> None:
    Query("userId", description="Only posts by this user")
    Body(description="The new user")
    PathParam(description="The user's ID")
    with pytest.raises(TypeError):
        Query("userId", "Only posts by this user")  # type: ignore[arg-type, call-arg]  # pyright: ignore[reportCallIssue]
    with pytest.raises(TypeError):
        PathParam("The user's ID")  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
    with pytest.raises(TypeError):
        PathParam(key="id")  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
