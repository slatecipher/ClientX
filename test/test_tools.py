"""Tools: endpoints described for a model, and called with its arguments."""

import json
import re
from collections.abc import Callable, Iterator
from typing import Annotated, Any, BinaryIO

import httpx2
import pytest
from pydantic import BaseModel, Field

from clientx import AsyncClientX, ClientX, DefinitionError, File, Header, Json, Query, Resource, Response, Send, method
from clientx.tools import Tool, ToolError, ToolOptions, list_tools, tool

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


class Order(BaseModel):
    id: int
    pet_id: int = Field(alias="petId")


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

        @method.get("/backup")
        def backup(self) -> bytes: ...

        @method.post("/upload")
        def upload(self, file: Annotated[BinaryIO, File()]) -> None: ...

        @method.get("/users")
        def users(self) -> list[User]: ...

    assert list(tools_of(API(BASE_URL))) == ["users"]


def test_include_in_tools_false_keeps_an_endpoint_out() -> None:
    class API(ClientX):
        @method.get("/status")
        def status(self) -> dict[str, Any]: ...

        @method.get("/config", include_in_tools=False)
        def config(self) -> dict[str, Any]: ...

    assert list(tools_of(API(BASE_URL))) == ["status"]


def test_an_endpoint_kept_out_of_the_tools_cant_set_tool_options() -> None:
    with pytest.raises(DefinitionError, match=r"sets both `include_in_tools=False` and `tool_options=`"):

        class API(ClientX):
            @method.get("/config", include_in_tools=False, tool_options=ToolOptions(read_only=True))
            def config(self) -> dict[str, Any]: ...


def test_a_private_name_isnt_a_tool() -> None:
    class Hidden(Resource, prefix="/hidden"):
        @method.get()
        def search(self) -> None: ...

    class Groups(Resource, prefix="/groups"):
        @method.delete("/{name}")
        def _delete(self, name: str) -> None: ...

        @method.get()
        def _search(self) -> None: ...

        search = _search

    class API(ClientX):
        groups = Groups()
        _hidden = Hidden()

    # Nothing on a private resource either, and a second name that isn't
    # private is listed.
    assert list(tools_of(API(BASE_URL))) == ["groups_search"]


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


def test_a_models_fields_are_named_as_in_python_not_by_alias(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.post("/orders")
        def place(self, order: Annotated[Order, Json()]) -> list[Order]:
            """Place an order."""
            ...

    sent: list[httpx2.Request] = []
    tool = tools_of(API(BASE_URL, transport=mock_transport(sent, json=[{"id": 3, "petId": 7}])))["place"]
    result = tool.call({"order": {"id": 3, "pet_id": 7}})

    fields = {"id": {"type": "integer"}, "pet_id": {"type": "integer"}}
    assert tool.input_schema["properties"]["order"]["properties"] == fields
    assert tool.output_schema is not None
    assert tool.output_schema["items"]["properties"] == fields
    # The API gets its own names, and the model the schemas'.
    assert json.loads(sent[0].content) == {"id": 3, "petId": 7}
    assert result == [{"id": 3, "pet_id": 7}]


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


def test_tool_options_set_hints_and_the_http_method_gives_the_rest() -> None:
    class API(ClientX):
        @method.post("/search", tool_options=ToolOptions(read_only=True))
        def search(self) -> None: ...

        @method.get("/cart/add", tool_options=ToolOptions(read_only=False))
        def add_to_cart(self) -> None: ...

    tools = tools_of(API(BASE_URL))
    assert (tools["search"].read_only, tools["search"].destructive, tools["search"].idempotent) == (True, False, False)
    add = tools["add_to_cart"]
    assert (add.read_only, add.destructive, add.idempotent) == (False, False, True)


@pytest.mark.parametrize(
    ("verb", "options"),
    [
        pytest.param(method.post, ToolOptions(read_only=True, destructive=True), id="both-set"),
        pytest.param(method.get, ToolOptions(destructive=True), id="read-only-from-GET"),
    ],
)
def test_an_endpoint_cant_be_read_only_and_destructive(verb: Any, options: ToolOptions) -> None:
    with pytest.raises(DefinitionError, match=r"Endpoint '.*API\.act' can't be both read-only and destructive"):

        class API(ClientX):
            @verb("/thing", tool_options=options)
            def act(self) -> None: ...


def test_a_deprecated_endpoint_is_a_tool_that_says_so() -> None:
    class API(ClientX):
        @method.get("/v1/users/{user_id}", deprecated="Use get_user() instead.")
        def get_user_v1(self, user_id: int) -> User:
            """Fetch a user."""
            ...

        @method.get("/v2/users/{user_id}")
        def get_user(self, user_id: int) -> User:
            """Fetch a user."""
            ...

    tools = tools_of(API(BASE_URL))
    assert tools["get_user_v1"].deprecated == "Use get_user() instead."
    assert tools["get_user_v1"].description == "Deprecated: Use get_user() instead.\n\nFetch a user."
    assert (tools["get_user"].deprecated, tools["get_user"].description) == (None, "Fetch a user.")


def test_a_tool_has_its_endpoints_tags() -> None:
    class Users(Resource, prefix="/users", tags=["users"]):
        @method.get("/{user_id}", tags=["read"])
        def retrieve(self, user_id: int) -> None: ...

    class API(ClientX):
        users = Users()

    assert tools_of(API(BASE_URL))["users_retrieve"].tags == ("users", "read")


def test_a_tool_method_is_a_tool_beside_the_endpoints(mock_transport: MockTransport) -> None:
    class Teams(Resource, prefix="/teams", tags=["teams"]):
        @method.get("/{team_id}/members")
        def member_ids(self, team_id: int) -> list[int]: ...

        @method.get("/members/{user_id}")
        def member(self, user_id: int) -> User: ...

        @tool(read_only=True, tags=["composite"])
        def members(self, team_id: int) -> list[User]:
            """List a team's members, in full.

            Args:
                team_id: The team's ID.
            """
            return [self.member(user_id) for user_id in self.member_ids(team_id)]

    class API(ClientX):
        teams = Teams()

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/teams/7/members":
            return httpx2.Response(200, json=[1, 2])
        return httpx2.Response(200, json={"id": int(request.url.path.rsplit("/", 1)[1]), "name": "Ada"})

    tools = tools_of(API(BASE_URL, transport=mock_transport(handler=answer)))
    assert list(tools) == ["teams_member_ids", "teams_member", "teams_members"]
    members = tools["teams_members"]
    assert members.description == "List a team's members, in full."
    assert members.input_schema["properties"] == {"team_id": {"type": "integer", "description": "The team's ID."}}
    # Hints left out are False: there's no HTTP method to take them from.
    assert (members.read_only, members.destructive, members.idempotent) == (True, False, False)
    assert members.tags == ("teams", "composite")
    assert members.call({"team_id": "7"}) == [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Ada"}]


def test_a_tool_methods_http_error_names_only_the_http_method(mock_transport: MockTransport) -> None:
    class API(ClientX):
        @method.get("/users/{user_id}")
        def user(self, user_id: int) -> User: ...

        @tool()
        def users(self, user_ids: list[int]) -> list[User]:
            """Fetch several users."""
            return [self.user(user_id) for user_id in user_ids]

    users = tools_of(API(BASE_URL, transport=mock_transport(status=404, json={"detail": "No such user."})))["users"]
    with pytest.raises(ToolError) as caught:
        users.call({"user_ids": [1]})
    assert str(caught.value) == 'users: the API answered 404 Not Found to a GET request: {"detail":"No such user."}'


def test_an_endpoint_cant_also_be_a_tool_method() -> None:
    message = r"'.*API\.retrieve' is an endpoint, so it's a tool already"
    with pytest.raises(DefinitionError, match=message):

        class API(ClientX):
            @tool()
            @method.get("/users/{user_id}")
            def retrieve(self, user_id: int) -> User: ...

    with pytest.raises(DefinitionError, match=message):

        class OtherAPI(ClientX):
            @method.get("/users/{user_id}")
            @tool()
            def retrieve(self, user_id: int) -> User:
                """Fetch a user."""
                ...


def undocumented(self: ClientX) -> None: ...


def unannotated(self: ClientX):
    """Do something."""


def binary(self: ClientX) -> bytes:
    """Do something."""
    return b""


def no_self() -> None:
    """Do something."""


def variadic(self: ClientX, *user_ids: int) -> None:
    """Do something."""


def documented(self: ClientX) -> None:
    """Do something."""


def _private(self: ClientX) -> None:
    """Do something."""


@pytest.mark.parametrize(
    ("decorator", "func", "message"),
    [
        pytest.param(tool(), _private, "Tool '_private' has a private name", id="private name"),
        pytest.param(tool(), undocumented, "Tool 'undocumented' needs a docstring", id="no docstring"),
        pytest.param(tool(), unannotated, "Tool 'unannotated' needs a return annotation", id="no return annotation"),
        pytest.param(tool(), binary, "Tool 'binary' can't return bytes", id="bytes"),
        pytest.param(tool(), no_self, "Tool 'no_self' needs a positional first parameter", id="no self"),
        pytest.param(tool(), variadic, "Tool 'variadic' can't take `*user_ids`", id="*args"),
        pytest.param(
            tool(read_only=True, destructive=True),
            documented,
            "Tool 'documented' can't be both read-only and destructive",
            id="read-only and destructive",
        ),
    ],
)
def test_a_tool_method_is_checked_when_decorated(
    decorator: Callable[[Callable[..., Any]], Callable[..., Any]], func: Callable[..., Any], message: str
) -> None:
    with pytest.raises(DefinitionError, match=re.escape(message)):
        decorator(func)


def test_a_tool_method_is_its_classs_kind() -> None:
    with pytest.raises(DefinitionError, match=r"Tool '.*API\.fetch' is `async def`, so it can't be a tool of"):

        class API(ClientX):
            @tool()
            async def fetch(self) -> None:
                """Fetch something."""


def test_a_tool_method_with_no_json_form_raises_when_listed() -> None:
    class API(ClientX):
        @tool()
        def upload(self, file: BinaryIO) -> None:
            """Upload a file."""

    with pytest.raises(DefinitionError, match=r"Tool '.*API\.upload' can't be described for a model"):
        list_tools(API(BASE_URL))


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
