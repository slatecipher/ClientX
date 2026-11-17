# pyright: reportUnnecessaryTypeIgnoreComment=true, reportUntypedFunctionDecorator=true
# mypy: disable-error-code="empty-body"
"""Static typing contract: endpoints keep their signatures for type checkers.

An endpoint with ``decoder=`` must return what its decoder returns.

Pyright and mypy both check this file in the blocking ``make typecheck`` step,
so CI fails if users of either checker would lose an endpoint's signature:

- ``assert_type`` fails if the inferred type isn't exactly the expected one.
- Each line that must be rejected has one comment per checker:
  ``# type: ignore[code]`` for mypy, then ``# pyright: ignore[rule]``. Pyright
  doesn't read mypy's comments (``enableTypeIgnoreComments = false`` in
  ``pyproject.toml``), so each checker reports its own comment if it's unused,
  and code that should be rejected but isn't gets reported.
- A method the decorator rejects is reported at the decorator. Pyright reports
  it three times: no matching overload (``reportCallIssue``), the mismatch
  (``reportArgumentType``), and the decorator's result being unknown
  (``reportUntypedFunctionDecorator``).
- ``reportUntypedFunctionDecorator`` is on because pyright otherwise hides an
  untyped decorator by falling back to the undecorated signature; mypy would see
  ``Any``.
- mypy's ``empty-body`` check is off, as users of mypy need, because endpoint
  bodies are ``...``.

The tests also run under pytest, against a transport of their own:
``make typecheck`` checks this file alone, so it doesn't use the fixtures in
``conftest.py``.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Annotated, Any, assert_type

import httpx2
import pytest
from pydantic import BaseModel

from clientx import AsyncClientX, AsyncResource, ClientX, DefinitionError, Query, Resource, Response, method


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def get(self, user_id: int) -> User: ...


class API(ClientX):
    users = Users()

    @method.get("/users")
    def list_users(self, page: Annotated[int, Query(ge=1)] = 1) -> list[User]: ...

    @method.get("/health")
    def health(self) -> Response: ...

    @method.get("/logs")
    def logs(self) -> Iterator[str]: ...

    @method.delete("/users/{user_id}")
    def delete_user(self, user_id: int, /) -> None: ...


class AsyncUsers(AsyncResource, prefix="/users"):
    @method.get("/{user_id}")
    async def get(self, user_id: int) -> User: ...


class AsyncAPI(AsyncClientX):
    users = AsyncUsers()

    @method.get("/logs")
    async def logs(self) -> AsyncIterator[str]: ...


def answering(**response: Any) -> httpx2.MockTransport:
    """Return a transport that answers ``httpx2.Response(200, **response)``."""
    return httpx2.MockTransport(lambda request: httpx2.Response(200, **response))


def test_endpoints_keep_their_return_types() -> None:
    api = API("https://api.example.com", transport=answering(json=[{"id": 1, "name": "Ada"}]))
    assert_type(api.list_users(), list[User])
    assert_type(api.health(), Response)
    assert_type(api.delete_user(1), None)


def test_endpoints_keep_their_parameters() -> None:
    api = API("https://api.example.com", transport=answering(json=[]))
    api.list_users(page=2)
    api.list_users(page="2")  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        api.delete_user(user_id=1)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_resource_endpoints_keep_their_signatures() -> None:
    api = API("https://api.example.com", transport=answering(json={"id": 1, "name": "Ada"}))
    assert_type(api.users.get(1), User)
    with pytest.raises(TypeError):
        api.users.get()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_streaming_endpoints_return_an_iterator() -> None:
    api = API("https://api.example.com", transport=answering(content=b"a\nb"))
    lines = api.logs()
    assert_type(lines, Iterator[str])
    assert list(lines) == ["a", "b"]


@pytest.mark.anyio
async def test_async_endpoints_keep_their_signatures() -> None:
    api = AsyncAPI("https://api.example.com", transport=answering(json={"id": 1, "name": "Ada"}))
    assert_type(await api.users.get(1), User)
    with pytest.raises(TypeError):
        await api.users.get()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


@pytest.mark.anyio
async def test_async_streaming_endpoints_return_an_async_iterator() -> None:
    api = AsyncAPI("https://api.example.com", transport=answering(content=b"a\nb"))
    lines = await api.logs()
    assert_type(lines, AsyncIterator[str])
    assert [line async for line in lines] == ["a", "b"]


# decoder=: the endpoint returns what its decoder returns.


class Event(BaseModel):
    id: int


def status_of(response: httpx2.Response) -> int:
    return response.status_code


def decode_events(response: httpx2.Response) -> Iterator[Event]:
    for line in response.iter_lines():
        yield Event.model_validate_json(line)


async def decode_async_events(response: httpx2.Response) -> AsyncIterator[Event]:
    async for line in response.aiter_lines():
        yield Event.model_validate_json(line)


class Decoded(ClientX):
    @method.post("/jobs", decoder=status_of)
    def submit(self) -> int: ...

    @method.get("/events", decoder=decode_events)
    def events(self) -> Iterator[Event]: ...

    @method.get("/text", decoder=lambda response: response.text)
    def text(self) -> str: ...

    @method.post("/jobs", decoder=status_of)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def mismatched(self) -> str: ...


class AsyncDecoded(AsyncClientX):
    @method.post("/jobs", decoder=status_of)
    async def submit(self) -> int: ...

    @method.get("/events", decoder=decode_async_events)
    async def events(self) -> AsyncIterator[Event]: ...

    @method.post("/jobs", decoder=status_of)  # type: ignore[type-var, arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    async def mismatched(self) -> str: ...


def test_a_decoded_endpoint_returns_what_its_decoder_returns() -> None:
    api = Decoded("https://api.example.com", transport=answering(content=b'{"id": 1}\n'))
    assert_type(api.submit(), int)
    assert_type(api.events(), Iterator[Event])
    assert_type(api.text(), str)
    assert (api.submit(), list(api.events()), api.text()) == (200, [Event(id=1)], '{"id": 1}\n')


@pytest.mark.anyio
async def test_a_decoded_async_endpoint_returns_what_its_decoder_returns() -> None:
    api = AsyncDecoded("https://api.example.com", transport=answering(content=b'{"id": 1}\n'))
    assert_type(await api.submit(), int)
    events = await api.events()
    assert_type(events, AsyncIterator[Event])
    assert [event async for event in events] == [Event(id=1)]


def test_a_decoded_async_def_endpoint_needs_an_async_client() -> None:
    with pytest.raises(DefinitionError):

        class Wrong(ClientX):
            @method.post("/jobs", decoder=status_of)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
            async def submit(self) -> int: ...


# The kind of class an endpoint is on. An `async def` endpoint on a sync class
# can't be rejected here: to a type checker it's a `def` that returns a
# coroutine. The check when the class is defined catches it.


def test_a_def_endpoint_needs_a_sync_class() -> None:
    with pytest.raises(DefinitionError):

        class WrongClient(AsyncClientX):
            @method.get("/health")  # type: ignore[type-var]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
            def health(self) -> None: ...

    with pytest.raises(DefinitionError):

        class WrongResource(AsyncResource):
            @method.get("/health")  # type: ignore[type-var]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
            def health(self) -> None: ...
