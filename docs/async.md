# Async Clients

For async code, such as an asyncio app, a FastAPI service, or an MCP server, subclass `AsyncClientX` instead of `ClientX`, and write endpoints as `async def` methods with the same decorators. Await an endpoint to send its request and get the decoded result:

```python
import asyncio
from typing import Annotated

from clientx import AsyncClientX, AsyncResource, Query, method
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from pydantic import BaseModel, TypeAdapter


class User(BaseModel):
    id: int
    name: str


class Users(AsyncResource, prefix="/users"):
    @method.get("/{user_id}", decoder=ModelDecoder(User))
    async def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get(decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    async def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(AsyncClientX, base_url="https://api.example.com", user_agent="example-app/1.0"):
    users = Users()


async def main() -> None:
    async with ExampleAPI() as api:
        user = await api.users.retrieve(42)  # GET /users/42 -> User
        # Several requests at once, sharing the client's connections:
        ada, grace = await asyncio.gather(api.users.retrieve(1), api.users.retrieve(2))


asyncio.run(main())
```

- Everything else works as it does for `ClientX`: parameters and request parts, decoders, the class arguments and options (such as `timeout=`, `auth=`, `raise_for_status=` and `validate_arguments=`), errors, and log records. Type checkers see `await api.users.retrieve(42)` as a `User`.
- Close the client with `async with`, or with `await api.aclose()` at shutdown for a long-lived client. As with `ClientX`, create one client and reuse it.
- `async def` endpoints go on an `AsyncClientX` or an `AsyncResource`, and `def` endpoints on a `ClientX` or a `Resource`. An `AsyncResource` mounts only on an `AsyncClientX` or another `AsyncResource`. Mixing them raises an error when the class is defined, and type checkers report it at the decorator.
- `transport=` and `mounts=` take async transports (`httpx2.MockTransport` works for both kinds of client), and event hooks must be `async` functions: see httpx2's [Event Hooks](https://pydantic.dev/docs/httpx2/advanced/event-hooks/). An `auth=` class works for both kinds.
- Plain methods can be `async def` too, and await endpoints through `self`, for example to follow pages (see [Plain methods](resources.md#plain-methods)).
- ClientX itself only awaits httpx2, so a client runs on any event loop httpx2 supports, such as asyncio or trio.

[`examples/jsonplaceholder_async_example.py`](https://github.com/slatecipher/ClientX/blob/mainline/examples/jsonplaceholder_async_example.py) fetches data from a real public API, one request at a time and all at once.

## Streaming

An `async def` endpoint streams with an async stream decoder, and returns an async iterator: annotate it `-> AsyncIterator[...]`.

```python
from collections.abc import AsyncIterator

from clientx import AsyncClientX, method
from clientx.decoders import AsyncStreamLinesDecoder


class EventsAPI(AsyncClientX, base_url="https://api.example.com"):
    @method.get("/events", decoder=AsyncStreamLinesDecoder())
    async def events(self) -> AsyncIterator[str]: ...


async def print_events() -> None:
    async with EventsAPI() as api:
        async for line in await api.events():
            print(line)
```

- `AsyncStreamLinesDecoder` yields text lines, and `AsyncStreamChunksDecoder(chunk_size=...)` yields byte chunks. To write your own, subclass `AsyncStreamDecoder` with an `async def __call__` that yields. A sync stream decoder, such as `StreamLinesDecoder`, raises an error on an `async def` endpoint that names the one to use.
- Awaiting the endpoint sends the request and raises for a 4xx or 5xx response, before iteration starts.
- The connection is released when iteration finishes or fails, or when the iterator is closed. If you stop early, it's released when the iterator is garbage-collected. To release it right away, use `StreamResponseDecoder` with `-> Response`, and close the response yourself: read it with `aiter_bytes()` or `aiter_lines()`, then call `await response.aclose()`.

## AI tools and MCP

`list_tools()` takes an async client too. Its tools have `is_async` set: call them with `await tool.acall(arguments)` (`tool.call()` raises `TypeError`). `run_mcp_server()` and `create_mcp_server()` serve an async client, awaiting its tools on the server's event loop. See [AI tools and MCP](ai-tools.md).

## Testing

`httpx2.MockTransport` serves async clients too, with the same handler. Run the tests with an async test plugin, such as anyio's, which comes with httpx2:

```python
import httpx2
import pytest


@pytest.mark.anyio
async def test_retrieve_decodes_the_user() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    async with ExampleAPI(transport=httpx2.MockTransport(handler)) as api:
        assert await api.users.retrieve(42) == User(id=42, name="Ada")
```

See [Testing](testing.md) for what to check on the requests a client sends.
