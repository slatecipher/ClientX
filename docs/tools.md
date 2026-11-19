# AI Tools

A ClientX client already describes each of its endpoints: its name, its docstring, and the types of its arguments and result. `clientx.tools` turns that into tools a model can call. `list_tools(client)` returns one `Tool` per endpoint, and `tool.call(arguments)` calls it with the arguments the model chose, through the client, with its base URL, auth and settings:

<!-- docs_src/tools/list_tools.py -->
```python
from typing import Annotated

from clientx import ClientX, Json, Query, Resource, method
from clientx.tools import ToolError, list_tools
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get()
    def search(self, name: Annotated[str | None, Query(description="Only users with this name.")] = None) -> list[User]:
        """List users."""
        ...

    @method.post()
    def create(self, user: Annotated[NewUser, Json()]) -> User:
        """Create a user.

        Args:
            user: The user to create. Its name must be unique.
        """
        ...


class ExampleAPI(ClientX, base_url="https://api.example.com"):
    users = Users()


api = ExampleAPI()
tools = {tool.name: tool for tool in list_tools(api)}  # users_search, users_create
create = tools["users_create"]
print(create.description)  # Create a user.
print(create.input_schema)  # {"properties": {"user": {"description": "The user to create. ...", ...}}, ...}

try:
    user = create.call({"user": {"name": "Ada"}})  # {"id": 1, "name": "Ada"}
except ToolError as error:
    print(error)  # users_create: the API answered 409 Conflict to POST /users: {"detail":"name taken"}
```

`clientx.tools` doesn't depend on any AI library. Register the tools with the framework your model runs in, such as an MCP server: each tool has what a framework asks for (see [Using a framework](#using-a-framework)).

## What a tool has

| Attribute | What it is |
|---|---|
| `name` | The endpoint's attribute path from the client, joined with `_`: `api.users.create` is `users_create`. |
| `description` | The endpoint's docstring, up to its first section, such as `Args:`. Without a docstring, the method and path: `GET /users/{user_id}`. |
| `input_schema` | The JSON Schema of the arguments: an object with one property per parameter, named as in the method. |
| `output_schema` | The JSON Schema of the result, from the return annotation, or `None` for `-> None`. |
| `read_only`, `destructive`, `idempotent` | Hints from the HTTP method: `GET`, `HEAD` and `OPTIONS` only read; `PUT`, `PATCH` and `DELETE` can change or delete what's there; and `GET`, `HEAD`, `OPTIONS`, `PUT` and `DELETE` have the same effect when called twice. |
| `is_async` | The endpoint is `async def`, so the tool is called with `await tool.acall(arguments)` instead of `call()`. |

Every endpoint on the client, and on the resources mounted on it, is a tool, except one a model can't use well: an endpoint that streams (`-> Iterator[...]` or `stream=True`), one that returns the raw `Response`, and one with an argument that has no JSON form, such as a binary file. An endpoint's second name in its class is the same endpoint, so it's listed once.

## Descriptions

A model chooses a tool and fills in its arguments from what the tool says, so the descriptions matter:

- **The tool's description** is the endpoint's docstring, up to its first section. Put what the endpoint does, and when to use it, in the summary and the paragraphs after it.
- **An argument's description** is its helper's `description=`, such as `Query(description="...")`, or else its entry in the docstring's `Args:` section. A [Google-style](../CONTRIBUTING.md#docstrings) `Args:` section then serves a model, editors' hovers and `help()` at once.
- **The schemas are compact.** Pydantic's `title` on every property is left out, and a model or `type` alias is written in place rather than behind a `$ref`, unless it refers to itself. Constraints, such as `Query(ge=1)`, and defaults are kept.

## Calling a tool

`tool.call(arguments)` takes the arguments as a model sends them, a mapping from parameter names to JSON values, and returns the result as JSON-ready data, with a model dumped as Pydantic dumps it in JSON mode:

- Arguments are named as in the method, not by a helper's `alias=`, which is the name sent to the API.
- They're validated as Pydantic validates a call, leniently: `"7"` fits an `int`.
- Only the arguments the model gave are passed, so the rest keep their defaults, as in a Python call: a `Send(exclude_unset=True)` parameter the model left out isn't sent, and a JSON field left at `None` isn't sent as `null`.

On an `AsyncClientX`, call tools with `await tool.acall(arguments)`. `call()` on an async tool, or `acall()` on a sync one, raises `TypeError`.

## Errors

A call that fails raises `ToolError`, whose message is written for the model, so it can fix its arguments or report the problem. Its `tool` attribute names the tool, and the original error is its `__cause__`, for your logs:

| What went wrong | The message |
|---|---|
| The arguments don't fit | Each argument and its problem, without Pydantic's links: `The arguments don't fit users_search: limit: Input should be less than or equal to 100 (got 500). Nothing was sent.` |
| An argument can't be sent | The [`ArgumentError`](errors.md#argumenterror)'s message, such as an empty path value. |
| A 4xx or 5xx response | The status, the method and path template, and the API's own answer, up to 2,000 characters: `users_create: the API answered 409 Conflict to POST /users: {"detail":"name taken"}` |
| The request failed | The method, the path template and the kind of failure, such as `ConnectTimeout`. |
| The response doesn't fit the return annotation | Each mismatch, without the response's values. |

A message never holds the host or the query string, which can carry credentials from the client's `params=`. Any other exception, such as a decoder's own, or the `RuntimeError` of a closed client, isn't a tool call's failure, and reaches you unchanged.

## Using a framework

Each framework registers tools its own way, but asks for the same things:

- the tool's `name` and `description`;
- its arguments' JSON Schema, `input_schema`, and for structured results, `output_schema`;
- a handler that calls `tool.call(arguments)`, or `await tool.acall(arguments)`, and turns a `ToolError` into an error result with its message;
- for MCP, the hints `read_only`, `destructive` and `idempotent`, as its `readOnlyHint`, `destructiveHint` and `idempotentHint`.

A model can call any tool you register, so register only what it should use. For example, start with the `read_only` tools, and add others as you need them. The hints come from the HTTP method, so they can be wrong for an endpoint such as `POST /search`, which only reads.
