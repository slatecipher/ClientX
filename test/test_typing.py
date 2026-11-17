# pyright: reportUnnecessaryTypeIgnoreComment=true, reportUntypedFunctionDecorator=true
# mypy: disable-error-code="empty-body"
"""Static typing contract: decorated endpoints keep their signatures for type checkers.

Pyright and mypy both check this file in the blocking ``make typecheck`` step, so CI fails
if users of either checker would lose an endpoint's signature:

- ``assert_type`` fails if the inferred type isn't exactly the expected one.
- Each line that must be rejected has one comment per checker: ``# type: ignore[code]`` for
  mypy, then ``# pyright: ignore[rule]``. Pyright doesn't read mypy's comments
  (``enableTypeIgnoreComments = false`` in ``pyproject.toml``), so each checker reports its
  own comment if it's unused, and code that should be rejected but isn't gets reported.
- ``reportUntypedFunctionDecorator`` is on because pyright otherwise hides an untyped
  decorator by falling back to the undecorated signature; mypy would see ``Any``.
- mypy's ``empty-body`` check is off, as users of mypy need, because endpoint bodies are ``...``.

The tests also run under pytest, against a transport of their own: ``make typecheck`` checks
this file alone, so it doesn't use the fixtures in ``conftest.py``.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Annotated, Any, assert_type

import httpx2
import pytest
from pydantic import BaseModel

from clientx import AsyncClientX, AsyncResource, ClientX, Query, Resource, Response, method


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
    """Return a transport that answers every request with ``httpx2.Response(200, **response)``."""
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
