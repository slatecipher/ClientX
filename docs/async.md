# Async Clients

For async code, such as an asyncio app or a FastAPI service, subclass `AsyncClientX` instead of `ClientX`, and write endpoints as `async def` methods with the same decorators. Await an endpoint to send its request and get the decoded result:

```python
import asyncio
from typing import Annotated

from clientx import AsyncClientX, AsyncResource, Query, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(AsyncResource, prefix="/users"):
    @method.get("/{user_id}")
    async def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get()
    async def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(AsyncClientX, user_agent="example-app/1.0"):
    users = Users()


async def main() -> None:
    async with ExampleAPI("https://api.example.com") as api:
        user = await api.users.retrieve(42)  # GET /users/42, decoded into a User
        # Several requests at once, sharing the client's connections:
        ada, grace = await asyncio.gather(api.users.retrieve(1), api.users.retrieve(2))
        print(user.name, ada.name, grace.name)


asyncio.run(main())
```

- Everything else works as it does for `ClientX`: parameters, decoding, the `user_agent=` class argument, options such as `timeout=`, `auth=` and `raise_for_status=`, and errors. Type checkers see `await api.users.retrieve(42)` as a `User`.
- An `AsyncClientX` is an `httpx2.AsyncClient`. Close it with `async with`, or with `await api.aclose()` at shutdown for a long-lived client. As with `ClientX`, create one client and reuse it.
- `async def` endpoints go on an `AsyncClientX` or an `AsyncResource`, and `def` endpoints on a `ClientX` or a `Resource`. An `AsyncResource` mounts only on an `AsyncClientX` or another `AsyncResource`. Mixing them raises `DefinitionError` when the class is defined, and type checkers report a `def` endpoint on an async class at its decorator.
- `transport=` and `mounts=` take async transports (`httpx2.MockTransport` works for both kinds of client), and event hooks must be `async` functions. An `auth=` class works for both kinds.
- Plain methods can be `async def` too, and await endpoints through `self`, for example to follow pages (see [Plain methods](resources.md#plain-methods)).
- A streamed `Body()` on an `async def` endpoint is an async iterable of bytes, such as an async generator. A sync one, a `list[bytes]` included, raises `DefinitionError` when the class is defined, since an `httpx2.AsyncClient` can't send it (see [Raw content](requests.md#raw-content)).
- ClientX itself only awaits httpx2, so a client runs on any event loop httpx2 supports, such as asyncio or trio.

## Streaming

An `async def` endpoint streams with `-> AsyncIterator[str]` (text lines) or `-> AsyncIterator[bytes]` (chunks). Await the endpoint to send the request, then iterate:

```python
from collections.abc import AsyncIterator

from clientx import AsyncClientX, method


class EventsAPI(AsyncClientX):
    @method.get("/events")
    async def events(self) -> AsyncIterator[str]: ...


async def print_events() -> None:
    async with EventsAPI("https://api.example.com") as api:
        async for line in await api.events():
            print(line)
```

- Awaiting the endpoint sends the request, and raises for a 4xx or 5xx response, before iteration starts.
- The response is closed when iteration finishes or fails, or when you close the iterator with its `aclose()` method. If you stop early without closing it, it's closed when the iterator is garbage-collected. To control that yourself, use `stream=True` with `-> Response`, read the response with `aiter_bytes()` or `aiter_lines()`, and call `await response.aclose()` (see [The open response](responses.md#the-open-response)).
- `-> Iterator[...]` on an `async def` endpoint raises `DefinitionError`, naming the annotation to use.

To stream other items, pass an async generator as the decoder:

```python
from collections.abc import AsyncIterator

from clientx import AsyncClientX, Response, method
from pydantic import BaseModel


class Event(BaseModel):
    id: int
    kind: str


async def parse_events(response: Response) -> AsyncIterator[Event]:
    """Yield an event for each line of JSON."""
    async for line in response.aiter_lines():
        if line:
            yield Event.model_validate_json(line)


class EventsAPI(AsyncClientX):
    @method.get("/events", decoder=parse_events)
    async def watch(self) -> AsyncIterator[Event]: ...
```

## Testing

`httpx2.MockTransport` serves async clients too, with the same handler. Run the tests with an async test plugin, such as anyio's, which comes with httpx2:

```python
import httpx2
import pytest
from clientx import AsyncClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(AsyncClientX):
    @method.get("/users/{user_id}")
    async def get_user(self, user_id: int) -> User: ...


@pytest.mark.anyio
async def test_get_user_decodes_the_user() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    async with UsersAPI("https://api.example.com", transport=httpx2.MockTransport(handler)) as api:
        assert await api.get_user(42) == User(id=42, name="Ada")
```

See [Testing](testing.md) for what to check on the requests a client sends.
