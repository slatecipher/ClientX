import importlib
import json
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx2
import pytest
from mcp import Client, types
from mcp.server.lowlevel import Server
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

import clientx.mcp
from clientx import ClientX, Resource, Response
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from clientx.mcp import create_mcp_server, run_mcp_server
from clientx.methods import delete, get


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @get("", decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def list_all(self) -> list[User]:
        """List users."""
        ...

    @delete("/{user_id}")
    def remove(self, user_id: int) -> None:
        """Delete a user."""
        ...


class ExampleAPI(ClientX):
    users = Users()

    @get("/health")
    def health(self) -> Response:
        """Check the service."""
        ...


def make_api(sent: list[httpx2.Request], fail: bool = False) -> ExampleAPI:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if fail:
            raise httpx2.ConnectError("connection refused", request=request)
        sent.append(request)
        if request.url.path == "/users":
            return httpx2.Response(200, json=[{"id": 1, "name": "Ada"}])
        if request.url.path == "/health":
            return httpx2.Response(200, text="ok")
        if request.method == "DELETE":
            return httpx2.Response(204)
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    return ExampleAPI("https://api.example.com", transport=httpx2.MockTransport(handler))


def run_with_client[T](server: Server[Any], scenario: Callable[[Client], Awaitable[T]]) -> T:
    async def main() -> T:
        async with Client(server) as client:
            return await scenario(client)

    return anyio.run(main)


def list_tools_over_mcp(server: Server[Any]) -> list[types.Tool]:
    async def scenario(client: Client) -> list[types.Tool]:
        return (await client.list_tools()).tools

    return run_with_client(server, scenario)


def call_over_mcp(server: Server[Any], name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    async def scenario(client: Client) -> types.CallToolResult:
        return await client.call_tool(name, arguments)

    return run_with_client(server, scenario)


def text_of(result: types.CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, types.TextContent)
    return content.text


def test_endpoints_are_listed_as_mcp_tools_with_their_schemas():
    tools = {tool.name: tool for tool in list_tools_over_mcp(create_mcp_server(make_api([]), read_only=False))}

    assert list(tools) == ["users_retrieve", "users_list_all", "users_remove", "health"]
    retrieve = tools["users_retrieve"]
    assert retrieve.description == "Fetch one user by ID."
    assert retrieve.input_schema["properties"] == {"user_id": {"title": "User Id", "type": "integer"}}
    assert retrieve.output_schema == User.model_json_schema(mode="serialization")


@pytest.mark.parametrize(
    ("name", "read_only", "destructive", "idempotent"),
    [("users_retrieve", True, False, True), ("users_remove", False, True, True)],
)
def test_http_method_hints_become_tool_annotations(name: str, read_only: bool, destructive: bool, idempotent: bool):
    tools = {tool.name: tool for tool in list_tools_over_mcp(create_mcp_server(make_api([]), read_only=False))}

    assert tools[name].annotations == types.ToolAnnotations(
        read_only_hint=read_only, destructive_hint=destructive, idempotent_hint=idempotent, open_world_hint=True
    )


def test_non_object_output_schemas_are_wrapped_with_their_definitions_at_the_top():
    tools = {tool.name: tool for tool in list_tools_over_mcp(create_mcp_server(make_api([]), read_only=False))}

    schema = tools["users_list_all"].output_schema
    assert schema is not None
    assert schema["type"] == "object"
    assert schema["required"] == ["result"]
    assert schema["properties"]["result"] == {"items": {"$ref": "#/$defs/User"}, "type": "array"}
    assert set(schema["$defs"]) == {"User"}
    assert tools["users_remove"].output_schema is None


def test_calling_a_tool_returns_structured_content_and_json_text():
    sent: list[httpx2.Request] = []
    result = call_over_mcp(create_mcp_server(make_api(sent)), "users_retrieve", {"user_id": 42})

    assert result.is_error is False
    assert result.structured_content == {"id": 42, "name": "Ada"}
    assert json.loads(text_of(result)) == {"id": 42, "name": "Ada"}
    assert [f"{r.method} {r.url.path}" for r in sent] == ["GET /users/42"]


@pytest.mark.parametrize(
    ("name", "arguments", "structured", "text"),
    [
        ("users_list_all", {}, {"result": [{"id": 1, "name": "Ada"}]}, '[{"id": 1, "name": "Ada"}]'),
        ("health", {}, {"status_code": 200, "body": "ok"}, '{"status_code": 200, "body": "ok"}'),
        ("users_remove", {"user_id": 7}, None, "null"),
    ],
)
def test_each_kind_of_result_is_returned(name: str, arguments: dict[str, Any], structured: Any, text: str):
    result = call_over_mcp(create_mcp_server(make_api([]), read_only=False), name, arguments)

    assert result.is_error is False
    assert result.structured_content == structured
    assert text_of(result) == text


def test_results_of_aliased_models_pass_the_mcp_clients_schema_check():
    class Company(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        employee_count: int = Field(alias="employeeCount")

    class CompaniesAPI(ClientX):
        @get("/companies", decoder=TypeAdapterDecoder(TypeAdapter(list[Company])))
        def list_all(self) -> list[Company]: ...

    api = CompaniesAPI(
        "https://api.example.com",
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=[{"employeeCount": 3187}])),
    )
    # The MCP client checks structured content against the tool's output schema.
    result = call_over_mcp(create_mcp_server(api), "list_all", {})

    assert result.is_error is False
    assert result.structured_content == {"result": [{"employeeCount": 3187}]}


def test_invalid_arguments_come_back_as_an_error_result_without_a_request():
    sent: list[httpx2.Request] = []
    result = call_over_mcp(create_mcp_server(make_api(sent)), "users_retrieve", {"user_id": "not a number"})

    assert result.is_error is True
    assert text_of(result).startswith("ValidationError: ")
    assert "user_id" in text_of(result)
    assert sent == []


def test_request_failures_come_back_as_an_error_result():
    result = call_over_mcp(create_mcp_server(make_api([], fail=True)), "users_retrieve", {"user_id": 42})

    assert result.is_error is True
    assert text_of(result) == "ConnectError: connection refused"


def test_error_statuses_come_back_as_an_error_result():
    api = ExampleAPI("https://api.example.com", transport=httpx2.MockTransport(lambda request: httpx2.Response(404)))

    result = call_over_mcp(create_mcp_server(api), "users_retrieve", {"user_id": 42})

    assert result.is_error is True
    assert text_of(result) == "HTTPStatusError: 404 Not Found for GET /users/42"


def test_an_error_status_never_shows_the_model_the_host_or_query_string():
    # An API that takes its key as a query parameter, set on the client as credentials should be.
    api = ExampleAPI(
        "https://user:password@api.example.com",
        params=httpx2.QueryParams({"api_key": "SECRET-KEY"}),
        transport=httpx2.MockTransport(lambda request: httpx2.Response(401, json={"error": "bad key"})),
    )

    text = text_of(call_over_mcp(create_mcp_server(api), "users_retrieve", {"user_id": 42}))

    assert text == 'HTTPStatusError: 401 Unauthorized for GET /users/42\nResponse body: {"error":"bad key"}'
    assert "SECRET-KEY" not in text
    assert "api.example.com" not in text
    assert "password" not in text


def test_a_long_error_body_is_cut_short():
    api = ExampleAPI(
        "https://api.example.com", transport=httpx2.MockTransport(lambda request: httpx2.Response(500, text="x" * 5000))
    )

    text = text_of(call_over_mcp(create_mcp_server(api), "users_retrieve", {"user_id": 42}))

    assert text == "HTTPStatusError: 500 Internal Server Error for GET /users/42\nResponse body: " + "x" * 1000 + "…"


def test_unknown_tool_comes_back_as_an_error_result():
    result = call_over_mcp(create_mcp_server(make_api([])), "users_explode", {})

    assert result.is_error is True
    assert text_of(result) == "Unknown tool: users_explode"


def test_only_read_only_endpoints_are_served_unless_asked():
    default = list_tools_over_mcp(create_mcp_server(make_api([])))
    everything = list_tools_over_mcp(create_mcp_server(make_api([]), read_only=False))

    assert [tool.name for tool in default] == ["users_retrieve", "users_list_all", "health"]
    assert [tool.name for tool in everything] == ["users_retrieve", "users_list_all", "users_remove", "health"]


def test_filters_choose_the_tools():
    server = create_mcp_server(make_api([]), read_only=True, exclude_tags=["nothing"])

    assert [tool.name for tool in list_tools_over_mcp(server)] == ["users_retrieve", "users_list_all", "health"]


def test_server_name_defaults_to_the_client_class_and_instructions_are_sent():
    async def scenario(client: Client) -> tuple[str, str | None]:
        info = client.server_info
        assert info is not None
        return info.name, client.instructions

    default = run_with_client(create_mcp_server(make_api([])), scenario)
    custom = run_with_client(create_mcp_server(make_api([]), name="example", instructions="Be careful."), scenario)

    assert default == ("ExampleAPI", None)
    assert custom == ("example", "Be careful.")


def test_run_mcp_server_serves_over_stdio(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, object, str]] = []

    @asynccontextmanager
    async def fake_stdio_server() -> AsyncGenerator[tuple[str, str]]:
        yield "stdin", "stdout"

    async def fake_run(self: Server[Any], read_stream: object, write_stream: object, options: Any) -> None:
        calls.append((read_stream, write_stream, self.name))

    monkeypatch.setattr(clientx.mcp, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(Server, "run", fake_run)

    run_mcp_server(make_api([]), name="example", read_only=True)

    assert calls == [("stdin", "stdout", "example")]


def test_importing_without_the_mcp_extra_explains_how_to_install_it(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.delitem(sys.modules, "clientx.mcp")

    with pytest.raises(ImportError, match=r'requires the "mcp" extra: pip install "clientx\[mcp\]"'):
        importlib.import_module("clientx.mcp")
