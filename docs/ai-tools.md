# Using a Client from AI Agents

`clientx.tools` describes a client's endpoints as tools for AI models. Each tool gets a name, a description, and JSON Schemas for its arguments and result, built from the method's signature, docstring, and types. `Tool.call` runs a tool with the arguments a model chose, through your client:

```python
from typing import Annotated

from clientx import ClientX, PathParam, Resource, method
from clientx.decoders import ModelDecoder
from clientx.tools import list_tools
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: Annotated[int, PathParam(description="The user's ID")]) -> User:
        """Fetch one user by ID."""
        ...


class ExampleAPI(ClientX):
    users = Users()


api = ExampleAPI("https://api.example.com")
tools = {tool.name: tool for tool in list_tools(api, read_only=True)}

tool = tools["users_retrieve"]
print(tool.description)  # Fetch one user by ID.
print(tool.input_schema)  # {"type": "object", "properties": {"user_id": {...}}, "required": ["user_id"], ...}
result = tool.call({"user_id": 42})  # GET /users/42, returns {"id": 42, "name": "..."}
```

Describe each parameter with its helper's `description=`, such as `Annotated[int | None, Query("userId", description="Only posts by this user")]`. A path parameter has no request-part helper, so use `PathParam(description=...)`: it only describes, and the parameter is still matched to its `{placeholder}` by name. A `PathParam()` parameter whose name isn't a placeholder in the path, including a resource prefix, raises `EndpointSignatureError` when the class is defined, and `PathParam` on a model field raises `MisplacedHelperError`. A description goes into the parameter's JSON Schema, which is where tools get it; it doesn't change requests. A `pydantic.Field(description=...)` on the same parameter still works, and wins if both are given.

To offer the tools to a model, pass each tool's `name`, `description`, and `input_schema` in the format your AI SDK expects, and call `tools[name].call(arguments)` when the model asks for a tool. With the Anthropic SDK, for example, that's `tools=[{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools.values()]`.

Each `Tool` has:

| Attribute | Value |
|---|---|
| `name` | The endpoint's attribute path joined with underscores: `users_retrieve` for `api.users.retrieve`. |
| `description` | The endpoint's docstring, or `"GET /users/{user_id}"` without one. It's what the model reads, so write docstrings. |
| `input_schema` | JSON Schema for the arguments. Describe a parameter with its helper's `description=` (see above). |
| `output_schema` | JSON Schema for the result: from the return type, `{"status_code", "body"}` for an endpoint that returns a `Response`, or `None` for one that returns nothing. |
| `read_only`, `destructive`, `idempotent` | Hints from the HTTP method: GET, HEAD, and OPTIONS are read-only; PUT, PATCH, and DELETE may change or delete data; GET, HEAD, OPTIONS, PUT, and DELETE are idempotent. |
| `method`, `path`, `tags`, `deprecated` | The endpoint's metadata. |
| `is_async` | The endpoint is `async def`, on an `AsyncClientX`: call the tool with `await tool.acall(arguments)` instead of `tool.call(arguments)`. Each raises `TypeError` for the other kind. |

`list_tools` takes filters: `read_only=True`, `include_tags=[...]`, `exclude_tags=[...]`, and `include_deprecated=True` (deprecated endpoints are left out by default). Streaming endpoints are always left out, and so is any endpoint whose types have no JSON Schema, such as an upload typed as a file object (`BinaryIO`), with a warning. An upload typed as `bytes`, such as `dict[str, bytes]`, has a schema (a string with `"format": "binary"`), so it's listed.

- **Expose only what an agent needs.** Tools can call `POST`, `PUT`, `PATCH`, and `DELETE` endpoints. `list_tools(client, read_only=True)` keeps only the read-only ones, which is what the MCP server serves by default. The hints come from the HTTP method, so an API that changes data on `GET` isn't flagged.
- **Keep credentials in the client's `auth=`** (see [Authentication](configuration.md#authentication)), never in endpoint parameters: parameters become arguments the model sees and fills in.
- `call` validates the arguments before sending anything and raises `pydantic.ValidationError` if they don't match. Request and decoder errors propagate. Most agent loops send the error text back to the model, but an `HTTPStatusError`'s message includes the full URL, query string included: if your client sends credentials as query parameters (`params=`), describe the error from `error.response.status_code` and `error.request.url.path` instead of sending `str(error)`. The MCP server does this for you.

## Serving a client over MCP

With the `mcp` extra, one call turns a client into an [MCP](https://modelcontextprotocol.io) server, so AI apps such as Claude Desktop, Claude Code, and other MCP clients can use your API without any agent code:

```bash
pip install "clientx[mcp]"
```

```python
# server.py
from clientx.mcp import run_mcp_server

from myapp.clients import ExampleAPI

run_mcp_server(ExampleAPI("https://api.example.com", auth=("user", "secret")))
```

Then point your MCP client at the command `python server.py`. In Claude Desktop's `claude_desktop_config.json`, for example:

```json
{"mcpServers": {"example-api": {"command": "python", "args": ["/path/to/server.py"]}}}
```

- Only read-only endpoints (`GET`, `HEAD`, and `OPTIONS`) are served unless you pass `read_only=False`, which serves `POST`, `PUT`, `PATCH`, and `DELETE` endpoints too. This is the one default that differs from `list_tools`, which also lists endpoints for docs and tooling: a model can change data only if you choose that.
- The full signature is `run_mcp_server(client, *, name=None, instructions=None, read_only=True, include_tags=None, exclude_tags=(), include_deprecated=False)`, and `create_mcp_server` takes the same arguments. The server's tools are exactly the ones `list_tools` returns with those filters, with the same names, descriptions, and schemas. `name=` (by default, the client's class name) and `instructions=` set what the server reports to MCP clients.
- The HTTP-method hints become MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), which MCP clients can use to ask for confirmation before changing data. Every tool also has `openWorldHint` set, because it reaches an external API.
- Results come back as structured content and as JSON text. Invalid arguments, request failures, and 4xx and 5xx responses come back as error results the model can read, and the server keeps running. A 4xx or 5xx error result has the status, the method and the request URL's path, and the start of the response body, but never the host or the query string, so credentials in query parameters don't reach the model. The path includes any path in the base URL (`/v1/users/42`), unlike a log record's `clientx_path` (`/users/42`).
- MCP messages use stdout, so don't print from the server process. Logging writes to stderr by default.
- The client can be a `ClientX` or an `AsyncClientX`. An async client's tools are awaited on the server's event loop, and a sync client's run in a worker thread, so they don't block it.
- `run_mcp_server` serves over stdio. For other transports, `create_mcp_server` returns the low-level `mcp.server.lowlevel.Server` to run yourself.

## Listing a Client's Endpoints

To build documentation, metadata files, or other tooling from a client, list its endpoints with `clientx.tools.list_tools()`. It includes endpoints on resources, and gives each one's name, HTTP method, full path, tags, docstring, deprecation status, and JSON Schemas for its arguments and result:

```python
from clientx import ClientX, Response, method
from clientx.tools import list_tools


class UsersClient(ClientX):
    @method.get("/users", tags=["public", "users"])
    def list_users(self) -> Response:
        """List all users."""
        ...


for tool in list_tools(UsersClient("https://api.example.com"), include_tags=["public"]):
    print(tool.method, tool.path, tool.tags, tool.description)  # GET /users ('public', 'users') List all users.
```

It leaves out streaming endpoints, and endpoints whose types have no JSON Schema (with a warning). The [`Tool` attributes](#using-a-client-from-ai-agents) at the top of this page list everything a tool describes.
