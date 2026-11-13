# Testing

Test a client without the network by passing an `httpx2.MockTransport` when you create it. The transport calls your handler with each `httpx2.Request` the client sends, and returns the `httpx2.Response` the handler builds, so a test can check what was sent and choose what comes back:

```python
from typing import Annotated

import httpx2
import pytest
from clientx import ClientX, Query
from clientx.decoders import ModelDecoder
from clientx.methods import get
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersClient(ClientX, base_url="https://api.example.com", user_agent="users-client/1.0"):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: int, fields: Annotated[str | None, Query()] = None) -> User:
        """Fetch one user by ID."""
        ...


def test_get_user_sends_the_request_and_decodes_the_user() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    client = UsersClient(transport=httpx2.MockTransport(handler))

    assert client.get_user(42, fields="name") == User(id=42, name="Ada")
    [request] = sent
    assert request.method == "GET"
    assert request.url.path == "/users/42"
    assert request.url.params["fields"] == "name"
    assert request.headers["User-Agent"] == "users-client/1.0"


def test_an_unknown_user_raises() -> None:
    def not_found(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"detail": "Not found"})

    client = UsersClient(transport=httpx2.MockTransport(not_found))

    with pytest.raises(httpx2.HTTPStatusError) as raised:
        client.get_user(7)

    assert raised.value.response.status_code == 404
    assert raised.value.response.json() == {"detail": "Not found"}
```

- `transport=` is an `httpx2.Client` option, so it works with any client, including one whose class ships its base URL. The client builds requests exactly as it would for the real API: the path, query string, headers, and body are all there to check.
- Build responses with `httpx2.Response(status, json=...)`, `text=`, `content=`, and `headers=`. Decoders, the 4xx and 5xx check, and logging run on them as on real responses.
- To test what a JSON body contains, read `json.loads(request.content)`; for form fields, `request.content` is URL-encoded.
- Annotate the handler with types, so the test type-checks in strict mode.
- `httpx2.MockTransport` serves an `AsyncClientX` too, with the same handler: see [Testing](async.md#testing) on the async page.

To test a client's tools, call them through `list_tools(client)` and `Tool.call`, with the same mock transport. To test an MCP server, connect the `mcp` package's `Client` to the server in memory, with no subprocess:

```python
import anyio
import httpx2
from clientx.mcp import create_mcp_server
from mcp import Client, types


def test_the_mcp_server_returns_the_user() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    server = create_mcp_server(UsersClient(transport=httpx2.MockTransport(handler)))

    async def call_tool() -> types.CallToolResult:
        async with Client(server) as mcp_client:
            return await mcp_client.call_tool("get_user", {"user_id": 42})

    result = anyio.run(call_tool)

    assert result.is_error is False
    assert result.structured_content == {"id": 42, "name": "Ada"}
```
