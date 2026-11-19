"""Tools: endpoints described for a model, and called with its arguments."""

import json
from collections.abc import Callable, Iterator
from typing import Annotated, Any, BinaryIO

import httpx2
import pytest
from pydantic import BaseModel

from clientx import AsyncClientX, ClientX, File, Header, Json, Query, Resource, Response, Send, method
from clientx.tools import Tool, ToolError, list_tools

type MockTransport = Callable[..., httpx2.MockTransport]

BASE_URL = "https://api.example.com"


class NewUser(BaseModel):
    name: str
    email: str | None = None


class User(BaseModel):
    id: int
    name: str


class Node(BaseModel):
    value: int
    children: list["Node"] = []


type Limit = Annotated[int, Query(ge=1, description="How many to return.")]


def tools_of(client: ClientX | AsyncClientX) -> dict[str, Tool]:
    return {tool.name: tool for tool in list_tools(client)}


def test_a_tool_is_named_by_its_path_from_the_client() -> None:
    class Members(Resource, prefix="/members"):
        @method.get()
        def search(self) -> None: ...

    class Teams(Resource, prefix="/teams"):
        members = Members()

        @method.get()
        def search(self) -> None: ...

        find = search

    class Base(ClientX):
        @method.get("/health")
        def health(self) -> None: ...

    class API(Base):
        teams = Teams()

    assert list(tools_of(API(BASE_URL))) == ["health", "teams_members_search", "teams_search"]


def test_an_endpoint_a_model_cant_use_isnt_a_tool() -> None:
    class API(ClientX):
        @method.get("/log")
        def log(self) -> Iterator[str]: ...

        @method.get("/download", stream=True)
        def download(self) -> Response: ...

        @method.get("/status")
        def status(self) -> Response: ...

        @method.post("/upload")
        def upload(self, file: Annotated[BinaryIO, File()]) -> None: ...

        @method.get("/users")
        def users(self) -> list[User]: ...

    assert list(tools_of(API(BASE_URL))) == ["users"]


def test_a_description_is_the_docstring_up_to_its_sections_or_the_request() -> None:
    class API(ClientX):
        @method.post("/users")
        def create(self, user: Annotated[NewUser, Json()]) -> User:
            """Create a user.

            The name must be unique.

            Args:
                user: The user to create.

            Raises:
                httpx2.HTTPStatusError: If the name is taken.
            """
            ...

        @method.get("/users/{user_id}")
        def retrieve(self, user_id: int) -> User: ...

    tools = tools_of(API(BASE_URL))
    assert tools["create"].description == "Create a user.\n\nThe name must be unique."
    assert tools["retrieve"].description == "GET /users/{user_id}"


def test_the_input_schema_is_compact_and_describes_each_argument() -> None:
    class API(ClientX):
        @method.post("/users")
        def create(
            self,
            user: Annotated[NewUser, Json()],
            request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
            limit: Limit = 20,
        ) -> Node:
            """Create a user.

            Args:
                user: The user to create.
                request_id: An ID to trace the request with,
                    echoed in the logs.
                limit: Not used: the helper's description wins.
            """
            ...

    tool = tools_of(API(BASE_URL))["create"]
    # Named as in the method, not by alias, with no titles, and models in place.
    assert tool.input_schema == {
        "additionalProperties": False,
        "properties": {
            "user": {
                "description": "The user to create.",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
                },
                "required": ["name"],
                "type": "object",
            },
            "request_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "An ID to trace the request with, echoed in the logs.",
            },
            "limit": {"default": 20, "description": "How many to return.", "minimum": 1, "type": "integer"},
        },
        "required": ["user"],
        "type": "object",
    }
    # A model that refers to itself stays in $defs.
    assert tool.output_schema is not None
    assert tool.output_schema["properties"]["children"]["items"] == {"$ref": "#/$defs/Node"}
    assert "Node" in tool.output_schema["$defs"]


@pytest.mark.parametrize(
    ("verb", "hints"),
    [
        pytest.param(method.get, (True, False, True), id="GET"),
        pytest.param(method.post, (False, False, False), id="POST"),
        pytest.param(method.put, (False, True, True), id="PUT"),
        pytest.param(method.patch, (False, True, False), id="PATCH"),
        pytest.param(method.delete, (False, True, True), id="DELETE"),
    ],
)
def test_the_hints_come_from_the_http_method(verb: Any, hints: tuple[bool, bool, bool]) -> None:
    class API(ClientX):
        @verb("/thing")
        def act(self) -> None: ...

    tool = tools_of(API(BASE_URL))["act"]
    assert (tool.read_only, tool.destructive, tool.idempotent) == hints
    assert tool.output_schema is None


def test_a_call_validates_leniently_and_passes_only_the_given_arguments(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.patch("/users/{user_id}")
        def update(
            self,
            user_id: int,
            /,
            name: Annotated[str | None, Json()] = None,
            nickname: Annotated[str | None, Json()] = None,
            page: Annotated[int, Query(), Send(exclude_unset=True)] = 1,
        ) -> User: ...

    sent: list[httpx2.Request] = []
    api = API(BASE_URL, transport=mock_transport(sent, json={"id": 7, "name": "Ada"}))
    assert tools_of(api)["update"].call({"user_id": "7", "name": "Ada"}) == {"id": 7, "name": "Ada"}
    # The positional-only user_id is passed, but nickname isn't sent as null,
    # nor page as 1.
    assert str(sent[0].url) == "https://api.example.com/users/7"
    assert json.loads(sent[0].content) == {"name": "Ada"}


def test_arguments_that_dont_fit_raise_before_sending(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users")
        def search(self, name: Annotated[str, Query()], limit: Annotated[int, Query(le=100)] = 20) -> list[User]: ...

    sent: list[httpx2.Request] = []
    tool = tools_of(API(BASE_URL, transport=mock_transport(sent)))["search"]
    with pytest.raises(ToolError) as caught:
        tool.call({"limit": 500, "userId": 1})
    assert str(caught.value) == (
        "The arguments don't fit search: name: is required; "
        "limit: Input should be less than or equal to 100 (got 500); "
        "userId: Unexpected keyword argument (got 1). Nothing was sent."
    )
    assert caught.value.tool == "search"
    assert sent == []


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        pytest.param(
            lambda request: httpx2.Response(409, json={"detail": "name taken"}),
            'search: the API answered 409 Conflict to GET /users: {"detail":"name taken"}',
            id="status",
        ),
        pytest.param(
            lambda request: httpx2.Response(500, text="x" * 2010),
            f"search: the API answered 500 Internal Server Error to GET /users: {'x' * 2000}... (10 more characters)",
            id="long body",
        ),
        pytest.param(
            lambda request: httpx2.Response(200, json=[{"id": "x", "name": "Ada"}]),
            "search: the API's answer to GET /users doesn't fit the endpoint's return annotation: "
            "0.id: Input should be a valid integer, unable to parse string as an integer.",
            id="response",
        ),
    ],
)
def test_a_failed_call_raises_a_message_for_the_model(
    mock_transport: MockTransport, handler: Callable[[httpx2.Request], httpx2.Response], message: str
) -> None:
    class API(ClientX):
        @method.get("/users")
        def search(self, name: Annotated[str, Query()]) -> list[User]: ...

    api = API(BASE_URL, params={"api_key": "secret"}, transport=mock_transport(handler=handler))
    with pytest.raises(ToolError) as caught:
        tools_of(api)["search"].call({"name": "Ada"})
    # The host and the query string, which holds the key, stay out.
    assert str(caught.value) == message
    assert isinstance(caught.value.__cause__, Exception)


def test_a_request_that_cant_be_sent_or_fails_raises_a_message_for_the_model() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    class API(ClientX):
        @method.get("/users/{user_id}")
        def retrieve(self, user_id: str) -> User: ...

    tool = tools_of(API(BASE_URL, transport=httpx2.MockTransport(refuse)))["retrieve"]
    with pytest.raises(ToolError, match=r"^retrieve couldn't send its request: Can't fill \{user_id\} with ''"):
        tool.call({"user_id": ""})
    with pytest.raises(ToolError) as caught:
        tool.call({"user_id": "7"})
    assert str(caught.value) == (
        "retrieve: the request to GET /users/{user_id} failed before the API answered (ConnectError)."
    )


@pytest.mark.anyio
async def test_an_async_tool_is_called_with_acall(mock_transport: MockTransport) -> None:
    class API(AsyncClientX):
        @method.get("/users/{user_id}")
        async def retrieve(self, user_id: int) -> User: ...

    class SyncAPI(ClientX):
        @method.get("/users/{user_id}")
        def retrieve(self, user_id: int) -> User: ...

    tool = tools_of(API(BASE_URL, transport=mock_transport(json={"id": 7, "name": "Ada"})))["retrieve"]
    assert tool.is_async
    assert await tool.acall({"user_id": 7}) == {"id": 7, "name": "Ada"}
    with pytest.raises(TypeError, match="call it with acall"):
        tool.call({"user_id": 7})
    with pytest.raises(TypeError, match="call it with call"):
        await tools_of(SyncAPI(BASE_URL))["retrieve"].acall({"user_id": 7})
