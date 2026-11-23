"""FastMCP: a client's tools served over MCP."""

import json
from collections.abc import Callable
from typing import Annotated

import httpx2
import pytest
from fastmcp import Client, FastMCP
from pydantic import BaseModel

from clientx import AsyncClientX, ClientX, Query, Response, method
from clientx.fastmcp import fastmcp_tool
from clientx.tools import list_tools

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class User(BaseModel):
    id: int
    name: str


class Node(BaseModel):
    value: int
    children: list["Node"] = []


def serve(client: ClientX | AsyncClientX) -> FastMCP:
    server = FastMCP("test")
    for tool in list_tools(client):
        server.add_tool(fastmcp_tool(tool))
    return server


@pytest.mark.anyio
async def test_a_tool_is_listed_as_clientx_describes_it(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users/{user_id}", tags=["ai"])
        def retrieve(self, user_id: int) -> User:
            """Fetch a user.

            Args:
                user_id: The user's ID.
            """
            ...

        @method.delete("/users/{user_id}")
        def remove(self, user_id: int) -> None:
            """Remove a user."""
            ...

    api = API(BASE_URL, transport=mock_transport(status=204))
    tools = {tool.name: tool for tool in list_tools(api)}
    async with Client(serve(api)) as client:
        listed = {tool.name: tool for tool in await client.list_tools()}
        removed = await client.call_tool("remove", {"user_id": 1})

    retrieve = listed["retrieve"]
    assert retrieve.description == "Fetch a user."
    assert retrieve.input_schema == tools["retrieve"].input_schema
    assert retrieve.output_schema == tools["retrieve"].output_schema
    assert retrieve.annotations is not None
    assert (retrieve.annotations.read_only_hint, retrieve.annotations.destructive_hint) == (True, False)
    assert retrieve.annotations.idempotent_hint is True
    assert fastmcp_tool(tools["retrieve"]).tags == {"ai"}
    # A tool that returns nothing has no output schema and no content.
    assert listed["remove"].output_schema is None
    assert (removed.is_error, removed.content) == (False, [])


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["def", "async def"])
async def test_a_call_validates_leniently_and_returns_structured_content(
    mock_transport: MockTransport, asynchronous: bool
) -> None:
    sent: list[httpx2.Request] = []
    transport = mock_transport(sent, json={"id": 7, "name": "Ada"})
    api: ClientX | AsyncClientX
    if asynchronous:

        class AsyncAPI(AsyncClientX):
            @method.get("/users/{user_id}")
            async def retrieve(self, user_id: int) -> User:
                """Fetch a user."""
                ...

        api = AsyncAPI(BASE_URL, transport=transport)
    else:

        class API(ClientX):
            @method.get("/users/{user_id}")
            def retrieve(self, user_id: int) -> User:
                """Fetch a user."""
                ...

        api = API(BASE_URL, transport=transport)

    async with Client(serve(api)) as client:
        result = await client.call_tool("retrieve", {"user_id": "7"})

    assert str(sent[0].url) == "https://api.example.com/users/7"
    assert result.structured_content == {"id": 7, "name": "Ada"}
    assert json.loads(result.content[0].text) == {"id": 7, "name": "Ada"}  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.anyio
async def test_a_result_that_isnt_an_object_is_wrapped_as_fastmcp_wraps_its_own(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users")
        def search(self, name: Annotated[str, Query()]) -> list[User]:
            """Search users by name."""
            ...

        @method.get("/motto")
        def motto(self) -> str:
            """Return the motto."""
            ...

        @method.get("/tree")
        def tree(self) -> list[Node]:
            """Return the tree."""
            ...

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/motto":
            return httpx2.Response(200, text="Ship it.")
        return httpx2.Response(200, json=[{"id": 1, "name": "Ada"}])

    api = API(BASE_URL, transport=mock_transport(handler=answer))
    users_schema = {tool.name: tool for tool in list_tools(api)}["search"].output_schema
    async with Client(serve(api)) as client:
        listed = {tool.name: tool for tool in await client.list_tools()}
        users = await client.call_tool("search", {"name": "Ada"})
        motto = await client.call_tool("motto", {})

    assert listed["search"].output_schema == {
        "type": "object",
        "properties": {"result": users_schema},
        "required": ["result"],
        "x-fastmcp-wrap-result": True,
    }
    # A model that refers to itself keeps $defs at the top, where its references
    # point.
    tree = listed["tree"].output_schema
    assert tree is not None
    assert "Node" in tree["$defs"]
    assert "$defs" not in tree["properties"]["result"]
    assert users.structured_content == {"result": [{"id": 1, "name": "Ada"}]}
    assert json.loads(users.content[0].text) == [{"id": 1, "name": "Ada"}]  # pyright: ignore[reportAttributeAccessIssue]
    # A string is the text as it is, and FastMCP's client unwraps the result.
    assert (motto.content[0].text, motto.data) == ("Ship it.", "Ship it.")  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.anyio
async def test_a_tool_error_reaches_the_model_and_other_errors_dont_leak(mock_transport: MockTransport) -> None:
    def broken(response: Response) -> int:
        raise RuntimeError(f"Can't read {response.request.url}")  # The URL holds the token.

    class API(ClientX):
        @method.get("/users/{user_id}")
        def retrieve(self, user_id: int) -> User:
            """Fetch a user."""
            ...

        @method.get("/count", decoder=broken)
        def count(self, token: Annotated[str, Query()]) -> int:
            """Count the users."""
            ...

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/count":
            return httpx2.Response(200, json=3)
        return httpx2.Response(404, json={"detail": "No such user."})

    api = API(BASE_URL, transport=mock_transport(handler=answer))
    async with Client(serve(api)) as client:
        missing = await client.call_tool("retrieve", {"user_id": 1}, raise_on_error=False)
        failed = await client.call_tool("count", {"token": "s3cret"}, raise_on_error=False)

    assert missing.is_error
    assert missing.content[0].text == (  # pyright: ignore[reportAttributeAccessIssue]
        'retrieve: the API answered 404 Not Found to GET /users/{user_id}: {"detail":"No such user."}'
    )
    assert failed.is_error
    assert failed.content[0].text == "count failed unexpectedly (RuntimeError)."  # pyright: ignore[reportAttributeAccessIssue]
