import logging
from collections.abc import Callable, Iterator
from enum import Enum
from typing import Annotated, Any, BinaryIO

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from clientx import ClientX, DeprecatedMessage, Query, Resource, Response, methods
from clientx.decoders import ModelDecoder, StreamLinesDecoder, TypeAdapterDecoder
from clientx.methods import delete, get, post
from clientx.tools import Tool, list_tools


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class Users(Resource, prefix="/users", tags=["users"]):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: Annotated[int, Field(description="The user's ID")]) -> User:
        """Fetch one user by ID."""
        ...

    @get("", decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def list_all(self, sort: Annotated[Sort, Query()] = Sort.NEWEST) -> list[User]:
        """List users."""
        ...

    @post("", tags=["write"])
    def create(self, json: dict[str, str]) -> Response:
        """Create a user."""
        ...

    @delete("/{user_id}", tags=["write", "danger"])
    def remove(self, user_id: int) -> None:
        """Delete a user."""
        ...


class ExampleAPI(ClientX):
    users = Users()

    @get("/health")
    def health(self) -> Response: ...

    @get("/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]: ...

    @get("/v1/health", deprecated=DeprecatedMessage("Use health()."))
    def legacy_health(self) -> Response:
        """Old health check."""
        ...


RESPONSES: dict[tuple[str, str], httpx2.Response] = {
    ("GET", "/users/42"): httpx2.Response(200, json={"id": 42, "name": "Ada"}),
    ("GET", "/users"): httpx2.Response(200, json=[{"id": 1, "name": "Ada"}]),
    ("POST", "/users"): httpx2.Response(201, json={"id": 2}),
    ("DELETE", "/users/7"): httpx2.Response(204),
    ("GET", "/health"): httpx2.Response(200, text="ok"),
}


@pytest.fixture
def make_api(mock_transport) -> Callable[[list[httpx2.Request]], ExampleAPI]:
    def answer(request: httpx2.Request) -> httpx2.Response:
        return RESPONSES.get((request.method, request.url.path), httpx2.Response(200, json={}))

    def make(sent: list[httpx2.Request]) -> ExampleAPI:
        return ExampleAPI("https://api.example.com", user_agent="tests/1.0", transport=mock_transport(sent, answer))

    return make


def tools_by_name(api: ClientX, **filters: Any) -> dict[str, Tool]:
    return {tool.name: tool for tool in list_tools(api, **filters)}


def test_tools_cover_client_and_resource_endpoints_in_definition_order(make_api):
    names = [tool.name for tool in list_tools(make_api([]))]

    # `events` streams and `legacy_health` is deprecated, so both are left out.
    assert names == ["users_retrieve", "users_list_all", "users_create", "users_remove", "health"]


def test_tool_describes_its_endpoint(make_api):
    tool = tools_by_name(make_api([]))["users_retrieve"]

    assert tool.description == "Fetch one user by ID."
    assert (tool.method, tool.path, tool.tags) == ("GET", "/users/{user_id}", ("users",))
    assert (tool.read_only, tool.destructive, tool.idempotent, tool.deprecated) == (True, False, True, False)
    assert tool.input_schema == {
        "additionalProperties": False,
        "properties": {"user_id": {"description": "The user's ID", "title": "User Id", "type": "integer"}},
        "required": ["user_id"],
        "title": "users_retrieve",
        "type": "object",
    }
    assert tool.output_schema == User.model_json_schema(mode="serialization")


def test_endpoint_without_a_docstring_is_described_by_method_and_path(make_api):
    tool = tools_by_name(make_api([]))["health"]

    assert tool.description == "GET /health"
    assert tool.output_schema == {
        "type": "object",
        "properties": {"status_code": {"type": "integer"}, "body": {}},
        "required": ["status_code", "body"],
    }


def test_defaults_and_enums_appear_in_the_input_schema(make_api):
    schema = tools_by_name(make_api([]))["users_list_all"].input_schema

    assert schema["properties"]["sort"] == {"$ref": "#/$defs/Sort", "default": "newest"}
    assert schema["$defs"]["Sort"]["enum"] == ["newest", "oldest"]
    assert "required" not in schema


def test_results_use_field_aliases_like_the_output_schema():
    class Company(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        employee_count: int = Field(alias="employeeCount")

    class CompaniesAPI(ClientX):
        @get("/companies/{company_id}", decoder=ModelDecoder(Company))
        def retrieve(self, company_id: int) -> Company: ...

    api = CompaniesAPI(
        "https://api.example.com",
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={"employeeCount": 3187})),
    )
    [tool] = list_tools(api)

    assert tool.output_schema is not None
    assert list(tool.output_schema["properties"]) == ["employeeCount"]
    assert tool.call({"company_id": 1}) == {"employeeCount": 3187}


def test_endpoint_returning_nothing_has_no_output_schema(make_api):
    assert tools_by_name(make_api([]))["users_remove"].output_schema is None


@pytest.mark.parametrize(
    ("verb", "read_only", "destructive", "idempotent"),
    [
        ("get", True, False, True),
        ("head", True, False, True),
        ("options", True, False, True),
        ("post", False, False, False),
        ("put", False, True, True),
        ("patch", False, True, False),
        ("delete", False, True, True),
    ],
)
def test_hints_follow_the_http_method(verb: str, read_only: bool, destructive: bool, idempotent: bool):
    def call(self: ClientX) -> Response: ...

    api_class = type("VerbAPI", (ClientX,), {"call": getattr(methods, verb)("/thing")(call)})
    [tool] = list_tools(api_class("https://api.example.com"))

    assert (tool.read_only, tool.destructive, tool.idempotent) == (read_only, destructive, idempotent)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"read_only": True}, ["users_retrieve", "users_list_all", "health"]),
        ({"include_tags": ["write"]}, ["users_create", "users_remove"]),
        ({"exclude_tags": ["danger"]}, ["users_retrieve", "users_list_all", "users_create", "health"]),
        (
            {"include_deprecated": True},
            ["users_retrieve", "users_list_all", "users_create", "users_remove", "health", "legacy_health"],
        ),
    ],
)
def test_filters_choose_which_endpoints_become_tools(filters: dict[str, Any], expected: list[str], make_api):
    assert list(tools_by_name(make_api([]), **filters)) == expected


def test_included_deprecated_endpoint_is_marked(make_api):
    assert tools_by_name(make_api([]), include_deprecated=True)["legacy_health"].deprecated is True


def test_call_validates_arguments_and_returns_json_friendly_results(make_api):
    sent: list[httpx2.Request] = []
    tools = tools_by_name(make_api(sent))

    assert tools["users_retrieve"].call({"user_id": "42"}) == {"id": 42, "name": "Ada"}
    assert tools["users_list_all"].call() == [{"id": 1, "name": "Ada"}]
    assert tools["users_list_all"].call({"sort": "oldest"}) == [{"id": 1, "name": "Ada"}]
    assert tools["users_create"].call({"json": {"name": "Ada"}}) == {"status_code": 201, "body": {"id": 2}}
    assert tools["users_remove"].call({"user_id": 7}) is None
    assert tools["health"].call() == {"status_code": 200, "body": "ok"}

    assert [(r.method, r.url.path, r.url.query.decode(), r.content) for r in sent] == [
        ("GET", "/users/42", "", b""),
        ("GET", "/users", "sort=newest", b""),
        ("GET", "/users", "sort=oldest", b""),
        ("POST", "/users", "", b'{"name":"Ada"}'),
        ("DELETE", "/users/7", "", b""),
        ("GET", "/health", "", b""),
    ]


@pytest.mark.parametrize(
    "arguments",
    [{"user_id": 42, "extra": 1}, {}, {"user_id": "not a number"}],
    ids=["unknown argument", "missing argument", "wrong type"],
)
def test_call_rejects_invalid_arguments_without_sending(arguments: dict[str, Any], make_api):
    sent: list[httpx2.Request] = []

    with pytest.raises(ValidationError):
        tools_by_name(make_api(sent))["users_retrieve"].call(arguments)
    assert sent == []


def test_tool_calls_go_through_the_client(caplog, make_api):
    caplog.set_level(logging.DEBUG, logger="clientx")
    sent: list[httpx2.Request] = []

    tools_by_name(make_api(sent))["users_retrieve"].call({"user_id": 42})

    assert sent[0].headers["User-Agent"] == "tests/1.0"
    [record] = [record for record in caplog.records if record.name == "clientx"]
    assert record.__dict__["clientx_endpoint"] == "Users.retrieve"


def test_model_parameters_are_passed_as_models():
    sent: list[httpx2.Request] = []

    class SignupAPI(ClientX):
        @post("/signup")
        def signup(self, payload: NewUser) -> None: ...

    api = SignupAPI(
        "https://api.example.com", transport=httpx2.MockTransport(lambda r: (sent.append(r), httpx2.Response(204))[1])
    )
    [tool] = list_tools(api)

    assert tool.input_schema["properties"]["payload"] == {"$ref": "#/$defs/NewUser"}
    tool.call({"payload": {"name": "Ada"}})
    assert sent[0].content == b'{"name":"Ada"}'


def test_positional_only_parameters_are_supported():
    sent: list[httpx2.Request] = []

    class ItemsAPI(ClientX):
        @get("/items/{item_id}")
        def retrieve(self, item_id: int, /) -> Response: ...

    api = ItemsAPI(
        "https://api.example.com", transport=httpx2.MockTransport(lambda r: (sent.append(r), httpx2.Response(200))[1])
    )
    list_tools(api)[0].call({"item_id": 3})

    assert sent[0].url.path == "/items/3"


def test_nested_resources_are_named_by_their_attribute_path():
    class Issues(Resource, prefix="/repos/{owner}/{repo}/issues"):
        @get("/{number}")
        def retrieve(self, owner: str, repo: str, number: int) -> Response: ...

    class Repos(Resource):
        issues = Issues()

    class GitAPI(ClientX):
        repos = Repos()

    assert [tool.name for tool in list_tools(GitAPI("https://api.example.com"))] == ["repos_issues_retrieve"]


def test_two_endpoints_with_the_same_tool_name_raise():
    class ClashAPI(ClientX):
        users = Users()

        @get("/users/{user_id}")
        def users_retrieve(self, user_id: int) -> Response: ...

    with pytest.raises(ValueError, match="Two endpoints map to the tool name 'users_retrieve'"):
        list_tools(ClashAPI("https://api.example.com"))


def test_invalid_tool_name_raises():
    class UnicodeAPI(ClientX):
        @get("/users")
        def récupérer(self) -> Response: ...

    with pytest.raises(ValueError, match="Tool name 'récupérer' is invalid"):
        list_tools(UnicodeAPI("https://api.example.com"))


def test_endpoint_without_a_json_schema_is_left_out_with_a_warning():
    class UploadAPI(ClientX):
        @post("/upload")
        def upload(self, files: dict[str, BinaryIO]) -> Response: ...

        @get("/health")
        def health(self) -> Response: ...

    with pytest.warns(
        UserWarning, match=r"left out endpoint '.*UploadAPI\.upload': its types have no JSON Schema"
    ) as caught:
        names = [tool.name for tool in list_tools(UploadAPI("https://api.example.com"))]

    assert names == ["health"]
    assert caught[0].filename == __file__


def test_tool_repr_shows_the_description_not_internals(make_api):
    text = repr(tools_by_name(make_api([]))["health"])

    assert text.startswith("Tool(name='health', description='GET /health'")
    assert "_function" not in text
