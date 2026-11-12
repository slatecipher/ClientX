# ClientX

[![PyPI](https://img.shields.io/pypi/v/clientx)](https://pypi.org/project/clientx/)
[![Python versions](https://img.shields.io/pypi/pyversions/clientx)](https://pypi.org/project/clientx/)
[![CI](https://github.com/slatecipher/ClientX/actions/workflows/ci.yml/badge.svg?branch=mainline)](https://github.com/slatecipher/ClientX/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/slatecipher/ClientX/blob/mainline/LICENSE)

Typed, declarative HTTP API clients for Python 3.12+.

## Overview

ClientX is a declarative API client framework designed to make writing and maintaining API clients easier while keeping the client contract explicit and well documented.

For client authors, ClientX reduces boilerplate by turning typed endpoint definitions into concrete `httpx2` requests and centralizing request/response behavior. For client consumers, it pushes API contracts and guard rails into the client itself, helping prevent avoidable runtime mistakes and making integrations more predictable.

The result is less scaffolding code and more focus on outcomes: authors spend less time on plumbing, and consumers spend less time guessing how to call your API correctly.

## Why ClientX

ClientX is inspired by FastAPI, which reads type hints to define server endpoints. ClientX applies the same idea to the client side:

- **The method signature is the contract.** Path placeholders, query parameters, headers, and bodies come from the method's parameters and annotations, so there's no request-building code to keep in sync.
- **Type checkers see real types.** Decorated methods keep their signatures, so editors and type checkers see the actual parameters and return types.
- **Mistakes surface early.** A missing return annotation or decoder raises an error when the class is defined, not on the first request.
- **Pydantic v2 throughout.** Send models as request bodies, query parameters, or headers, and decode responses into models.
- **Ready for AI agents.** `clientx.tools` turns a client's endpoints into tool definitions for AI models, built from the same signatures, docstrings, and types, and `clientx[mcp]` serves them as an MCP server in one call.
- **Built on httpx2.** Every `httpx2.Client` option is available, including auth, timeouts, proxies, and custom transports, and responses can be streamed.

ClientX is an independent project. It isn't affiliated with or endorsed by the FastAPI, Pydantic, or httpx2 projects.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Typed response handling with pluggable decoders.
- Path parameter rendering from method arguments (e.g. `"/users/{user_id}"`).
- Request payload mapping from parameter names, `Annotated` metadata, or Pydantic models.
- Built-in deprecation warnings per endpoint.
- Endpoint tags, for grouping endpoints and filtering the AI tools built from them.
- Full access to `httpx2.Client` configuration through `ClientX(...)` kwargs.
- Endpoints described as AI tools, with JSON Schemas and safety hints (`clientx.tools`).
- A client served as an MCP server in one call (`clientx[mcp]`).

## Project status

ClientX is a personal project that I maintain in my spare time. Issues and pull requests are welcome, but replies may take a while, and there is no guaranteed response time.

ClientX is pre-1.0, so the API may change between minor versions. Changes are listed in the [changelog](https://github.com/slatecipher/ClientX/blob/mainline/CHANGELOG.md).

## Install

```bash
pip install clientx
```

To serve a client as an MCP server, install the `mcp` extra: `pip install "clientx[mcp]"`.

Using an AI coding assistant? Point it at [llms.txt](https://github.com/slatecipher/ClientX/blob/mainline/llms.txt), a compact guide to ClientX's patterns and pitfalls.

## Quickstart

```python
from clientx import ClientX, Response
from clientx.methods import get


class UsersClient(ClientX):
    @get("/users/{user_id}")
    def get_user(self, user_id: str) -> Response:
        # Method body is not executed.
        # ClientX uses the signature + decorator metadata.
        ...


client = UsersClient("https://api.example.com")
response = client.get_user("42")
print(response.status_code)
```

## Defining Endpoints

Use decorators from `clientx.methods`:

- `get`
- `post`
- `put`
- `patch`
- `delete`
- `head`
- `options`

Each decorator accepts:

- `path` (optional; defaults to `""`, the base URL, or on a resource the prefix itself: `@get()` in a resource with `prefix="/users"` is `GET /users`)
- `decoder` (required when return type is not `Response` or `None`)
- `deprecated` (optional callable, including `DeprecatedMessage`)
- `tags` (optional list of labels; `list_tools()` can filter by them)
- `timeout` (optional per-endpoint `httpx2.Timeout` or seconds)
- `raise_for_status` (optional `True` or `False`; overrides the client's setting, see [Raising errors for 4xx and 5xx responses](#raising-errors-for-4xx-and-5xx-responses))
- `validate_arguments` (optional `True` or `False`; overrides the client's setting, see [Validating arguments](#validating-arguments))

```python
from clientx import ClientX, Response
from clientx.methods import post


class ItemsClient(ClientX):
    @post("/items")
    def create_item(self, json: dict[str, object]) -> Response:
        ...
```

### Empty method bodies and mypy

Endpoint bodies never run, so `...` is all they need. Pyright accepts this, but mypy reports `Missing return statement  [empty-body]` for every endpoint whose return type isn't `None`. Turn that one check off for your client modules, either at the top of the file:

```python
# mypy: disable-error-code="empty-body"
```

or in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "myapp.clients"
disable_error_code = ["empty-body"]
```

Mypy still checks everything else in those modules, including the return types of calls to your endpoints.

## Grouping Endpoints with Resources

For larger APIs, group related endpoints into `Resource` classes, much like FastAPI's `APIRouter`. Mount an instance on your client, and its endpoints send through the client's connection and configuration, so there's no second client to create or pass around:

```python
from pydantic import BaseModel

from clientx import ClientX, Resource, Response
from clientx.decoders import ModelDecoder
from clientx.methods import get, post


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users", tags=["users"]):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        ...

    @post()
    def create(self, json: dict[str, str]) -> Response:
        ...


class ExampleAPI(ClientX):
    users = Users()


api = ExampleAPI("https://api.example.com")
user = api.users.retrieve(42)  # GET /users/42
```

Type checkers see `api.users` as `Users`, and its endpoints keep their signatures.

- `prefix` is joined to the path of each endpoint in the class when the class is defined, so tools and logs show full paths. It's absolute: a resource's paths don't depend on where it's mounted. Put a prefix shared by the whole API, such as `/v1`, in the client's base URL instead.
- Placeholders in a prefix are filled from method arguments like any other: with `prefix="/repos/{owner}/{repo}"`, each endpoint needs `owner` and `repo` parameters.
- `tags` are added before each endpoint's own tags.
- Mount resources on other resources to nest them, for example `api.repos.issues.retrieve(...)`. Each keeps its own prefix.
- A resource doesn't refer to the client class, so resources can live in their own modules.
- Names that `ClientX` itself uses, such as `client` and `user_agent`, are free for endpoints on a resource.
- A subclass keeps its parent's prefix and tags unless it sets its own.
- An endpoint's name hides any other meaning of that name for the rest of the class body:
  - If an endpoint is named like a decorator, such as `get`, later decorators refer to that method instead. Import the module (`from clientx import methods`) and write `@methods.get(...)`.
  - If an endpoint is named `list` (or `dict`, `type`, ...), a later `list[Post]` in an annotation or a decorator argument fails when the class is defined: `TypeError: 'function' object is not subscriptable`. Pyright reports it too. Define that endpoint last in the class, or write `builtins.list[Post]` after it.
- Mount an instance (`users = Users()`), not the class. Calling an endpoint on a resource that isn't mounted on a client, such as `Users().retrieve(42)`, raises `UnboundResourceError`.

## Listing a Client's Endpoints

To build documentation, metadata files, or other tooling from a client, list its endpoints with `clientx.tools.list_tools()`. It includes endpoints on resources, and gives each one's name, HTTP method, full path, tags, docstring, deprecation status, and JSON Schemas for its arguments and result:

```python
from clientx import ClientX, Response
from clientx.methods import get
from clientx.tools import list_tools


class UsersClient(ClientX):
    @get("/users", tags=["public", "users"])
    def list_users(self) -> Response:
        """List all users."""
        ...


for tool in list_tools(UsersClient("https://api.example.com"), include_tags=["public"]):
    print(tool.method, tool.path, tool.tags, tool.description)  # GET /users ('public', 'users') List all users.
```

It leaves out streaming endpoints, and endpoints whose types have no JSON Schema (with a warning). See [Using a Client from AI Agents](#using-a-client-from-ai-agents) for everything a tool describes.

## Return Types and Decoders

ClientX enforces explicit return annotations:

- `-> Response`: returns raw `httpx2.Response`.
- `-> None`: sends request and returns `None`.
- Any other type: requires `decoder=...`.

A 4xx or 5xx response raises `httpx2.HTTPStatusError` before any decoder runs (see [Raising errors for 4xx and 5xx responses](#raising-errors-for-4xx-and-5xx-responses)). Otherwise, if you pass a decoder, it always runs and its output is returned, whatever the annotation.

A decoder is a callable that receives the raw `httpx2.Response` and returns the value that matches your method's return annotation. ClientX executes the HTTP request first, then passes the response into the decoder, and returns the decoder output to the caller.

Type checkers enforce the match: `decoder=ModelDecoder(User)` on a method annotated `-> str` is reported as an error, and so is a method annotated with anything other than `Response` or `None` that has no decoder.

In practice, decoders are where you define response parsing and validation behavior:

- Parse JSON/text/bytes from the response body.
- Validate and coerce payloads into typed Python objects.
- Build richer return objects that combine body data with headers/status metadata.

### `ModelDecoder`

```python
from pydantic import BaseModel

from clientx import ClientX
from clientx.decoders import ModelDecoder
from clientx.methods import get


class User(BaseModel):
    id: int
    email: str


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: str) -> User:
        ...
```

### `TypeAdapterDecoder`

```python
from pydantic import TypeAdapter

from clientx import ClientX
from clientx.decoders import TypeAdapterDecoder
from clientx.methods import get


UserList = TypeAdapter(list[dict[str, str]])


class UsersClient(ClientX):
    @get("/users", decoder=TypeAdapterDecoder(UserList))
    def list_users(self) -> list[dict[str, str]]:
        ...
```

### `FromResponseDecoder`

```python
from httpx2 import Response
from pydantic import BaseModel

from clientx import ClientX
from clientx.decoders import FromResponseDecoder
from clientx.methods import get


class SessionPayload(BaseModel):
    token: str
    status_code: int

    @classmethod
    def from_response(cls, response: Response) -> "SessionPayload":
        return cls(token=response.json()["token"], status_code=response.status_code)


class SessionClient(ClientX):
    @get("/session", decoder=FromResponseDecoder(SessionPayload))
    def get_session(self) -> SessionPayload:
        ...
```

### Vanilla decoders (`clientx.decoders`)

For lightweight cases, ClientX also ships simple function decoders:

- `json_decoder`: returns `response.json()` (`Any`).
- `content_decoder`: returns raw `response.content` (`bytes`).
- `text_decoder`: returns `response.text` (`str`).

```python
from typing import Any

from clientx import ClientX
from clientx.decoders import json_decoder, text_decoder
from clientx.methods import get


class HealthClient(ClientX):
    @get("/health", decoder=text_decoder)
    def health(self) -> str:
        ...


class MetadataClient(ClientX):
    @get("/metadata", decoder=json_decoder)
    def metadata(self) -> Any:
        ...
```

`json_decoder` does no validation, so its result is `Any`. For a typed result, validate it with `TypeAdapterDecoder(TypeAdapter(dict[str, object]))` or a `ModelDecoder`.

### Bring Your Own Decoder (BYOD)

You can pass any callable with signature `(response: httpx2.Response) -> T` as `decoder=...`. Type checkers require `T` to match your endpoint's return annotation.

Use BYOD when you need behavior that is specific to your API contract, such as envelope unwrapping, fallback parsing, or custom validation rules.

```python
from httpx2 import Response
from pydantic import BaseModel, TypeAdapter

from clientx import ClientX
from clientx.methods import get


class Item(BaseModel):
    id: int
    name: str


_item_list = TypeAdapter(list[Item])


def items_decoder(response: Response) -> list[Item]:
    payload = response.json()
    # Example: API returns {"data": {"items": [...]}}
    return _item_list.validate_python(payload["data"]["items"])


class ItemsClient(ClientX):
    @get("/items", decoder=items_decoder)
    def list_items(self) -> list[Item]:
        ...
```

The only requirement is that your decoder output matches the declared return annotation.

### Streaming responses

Stream decoders read the body incrementally instead of loading it into memory. The decoder decides whether a request streams, so there is no `stream=` flag:

```python
from collections.abc import Iterator

from clientx import ClientX
from clientx.decoders import StreamLinesDecoder
from clientx.methods import get


class EventsClient(ClientX):
    @get("/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]:
        ...


for line in EventsClient("https://api.example.com").events():
    print(line)
```

- `StreamLinesDecoder` yields text lines, and `StreamChunksDecoder(chunk_size=...)` yields byte chunks. To write your own, subclass `StreamDecoder`.
- The connection is released when iteration finishes, when the loop exits early (`break` or an exception), or when you call `.close()` on the returned iterator. If you keep a partly consumed iterator around, close it when you are done.
- To get the open streamed response itself, use `StreamResponseDecoder` with `-> Response`. You own that response: read it, iterate it to the end, or call `response.close()`.

```python
from clientx import ClientX, Response
from clientx.decoders import StreamResponseDecoder
from clientx.methods import get


class FilesClient(ClientX):
    @get("/files/{file_id}", decoder=StreamResponseDecoder())
    def download(self, file_id: str) -> Response:
        ...


response = FilesClient("https://api.example.com").download("42")
try:
    with open("file.bin", "wb") as f:
        for chunk in response.iter_bytes():
            f.write(chunk)
finally:
    response.close()
```

## Building Request Payloads

ClientX maps method arguments into request parts in this order:

1. Path placeholders (e.g. `{user_id}`) are consumed from arguments. Each value is converted like a query value (an `Enum` becomes its value, a `datetime` ISO 8601) and percent-encoded, so a value such as `"a/b"` or `"../admin"` stays one path segment and can't add a query string. For a value that spans segments, such as a file path, use `{file_path:path}`: slashes are kept, and each segment is still encoded. Any other converter raises `PathTemplateError` when the class is defined. A value that would change which path is called raises `PathValueError` before anything is sent: `None` (it would be sent as `null`), an empty value (`/users/{user_id}` with `""` would call `/users/`), or, in a `{name:path}` value, a leading, trailing, or doubled slash.
2. Each remaining argument goes to the first of these that matches:
   1. Its name is a request part: `json`, `params`, `data`, `files`, or `headers`. The name wins even over an annotation, so a parameter named `data` is always sent as form data.
   2. It's annotated with a request part: `Annotated[..., Query()]`, `Header()`, `Form()`, `Body()`, or `File()`.
   3. Its value is a Pydantic model, which is expanded field by field.
3. Arguments for the same request part are merged in parameter order, and later ones win: dicts are merged key by key, so a later `Header("X-Request-Id")` parameter overrides that key in an earlier `headers` dict, and any other value replaces the part. There's no warning, so put the parameter that should win last.

### By parameter name

```python
from clientx import ClientX, Response
from clientx.methods import get


class SearchClient(ClientX):
    @get("/search")
    def search(self, params: dict[str, object], headers: dict[str, str]) -> Response:
        ...
```

### With `Query`, `Header`, `Form`, `Body`, and `File`

Annotate a parameter with the helper for the request part it goes to:

| Helper | Request part | Example |
|---|---|---|
| `Query(key=None)` | Query parameters (`params`) | `Annotated[int \| None, Query("userId")]` |
| `Header(key=None)` | Headers | `Annotated[str, Header("Authorization")]` |
| `Form(key=None)` | Form data (`data`) | `Annotated[str, Form()]` |
| `Body()` | The JSON body (`json`) | `Annotated[UserChanges, Body()]` |
| `File()` | Multipart files (`files`) | `Annotated[dict[str, bytes], File()]` |

Every helper also takes `description=`, which describes the parameter or model field in its JSON Schema: it appears in any schema Pydantic builds from the annotation, such as a model's `model_json_schema()`, and in the argument schemas of [AI tools](#using-a-client-from-ai-agents). `PathParam(description=...)` does the same for a path parameter. A description never changes the request.

```python
from enum import Enum
from typing import Annotated

from clientx import Body, ClientX, Header, Query, Response
from clientx.methods import get, post


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class ItemsClient(ClientX):
    @get("/items")
    def list_items(
        self,
        item_type: Annotated[str, Query("type")],
        sort: Annotated[Sort, Query()] = Sort.NEWEST,
        page: Annotated[int | None, Query()] = None,
    ) -> Response:
        ...

    @post("/items")
    def create_item(
        self,
        token: Annotated[str, Header("Authorization")],
        payload: Annotated[dict[str, object], Body()],
    ) -> Response:
        ...
```

`list_items("book", Sort.OLDEST)` sends `GET /items?type=book&sort=oldest`. `page` is left out because it's `None`.

`Query`, `Header`, and `Form` send name-value pairs:

- `key` is the name the value is sent under, and it can differ from the parameter name. Without `key`, a single value (a string, number, or list) is sent under the parameter name, and a list repeats it (`?tag=a&tag=b`).
- `Header()` uses hyphens instead of underscores in the parameter name, so `request_id` is sent as `request-id`. A `key` is used exactly as given.
- A mapping, such as `dict[str, str]`, or a Pydantic model is merged into the part instead.
- Values are converted the way model fields are (see `DumpConfig` below): an `Enum` member becomes its `.value`, a `datetime` an ISO 8601 string, and a `UUID` a string. Numbers and booleans in headers are sent as text (`2`, `true`).
- A value of `None` is left out, so an optional parameter can default to `None`. To send an empty value, pass `""`.

`Body()` and `File()` take no key: they send the value as the JSON body or as the `files` mapping. Every helper takes `dump_config=` for Pydantic models (see `DumpConfig` below).

To reuse an annotation, name it with a `type` alias, plain or generic: `type UserId = Annotated[int | None, Query("userId")]`, or `type QueryParam[T] = Annotated[T, Query()]` used as `QueryParam[str]`.

A helper applies to the whole parameter or field, so use one helper, in the outermost `Annotated`, around the full type with `None` included: `Annotated[int | None, Query()]`, or `QueryParam[int | None]` with an alias. A helper nested inside another type, such as `Annotated[int, Query()] | None` or `list[Annotated[str, Query()]]`, and a second helper on the same parameter raise `MisplacedHelperError`: for a parameter when the class is defined, for a model field when the model is sent. If the request part depends on the value's type (a `str` header or a `dict` body, say), write separate endpoints.

The helpers are named like FastAPI's, but they do the opposite job: FastAPI's read the incoming request, and ClientX's build the outgoing one. In a FastAPI app that calls other APIs, import one of them under another name (`from clientx import Query as ClientQuery`), or use the module (`import clientx`, then `clientx.Query("userId")`).

### By Pydantic model

```python
from typing import Annotated

from pydantic import BaseModel

from clientx import ClientX, Header, Query, Response
from clientx.methods import post


class CreateUserPayload(BaseModel):
    api_key: Annotated[str, Header("X-Api-Key")]
    notify: Annotated[bool, Query()] = False
    name: str
    email: str


class UsersClient(ClientX):
    @post("/users")
    def create_user(self, payload: CreateUserPayload) -> Response:
        ...
```

`create_user(CreateUserPayload(api_key="k-1", name="Ada", email="ada@example.com"))` sends `POST /users?notify=false` with an `X-Api-Key` header and the JSON body `{"name": "Ada", "email": "ada@example.com"}`.

A model passed without a helper is expanded field by field. A field annotated with `Query`, `Header`, or `Form` follows the same rules as a parameter: a single value is sent under its `key`, or under its alias or field name, and a mapping is merged into the part. Fields annotated with `Body` or `File` are merged into that part, so their value must be a mapping or a model: any other value, `None` included, raises `UnconsumableArgumentError` when the model is sent. Unannotated fields go to the JSON body.

`None` values are never sent as query parameters, headers, or form fields, whether they come from a single value, a mapping, or a model field. A JSON body keeps them as `null`. To leave them out of a JSON body too, use `DumpConfig(exclude_none=True)`, shown below.

### Serialization control with `DumpConfig`

ClientX dumps models with `mode="json"` and `by_alias=True`. Dates, UUIDs, and decimals become JSON values, and each field is sent under its alias, which is usually the API's own name for it (`user_id: int = Field(alias="userId")`, or `alias_generator=to_camel` for a whole model).

`DumpConfig` takes these options of Pydantic's `model_dump`, and each one overrides ClientX's default:

| Option | Effect |
|---|---|
| `exclude_unset=True` | Send only the fields that were set. This is the usual choice for a PATCH. |
| `exclude_none=True` | Leave out `None` fields. Query parameters, headers, and form data always leave them out. |
| `exclude_defaults=True` | Leave out fields that still have their default value. |
| `include=...` / `exclude=...` | Send only the given fields, or leave them out, such as `exclude={"internal_note"}`. |
| `by_alias=False` | Send field names instead of aliases. |
| `mode="python"` | Keep Python objects such as `datetime`. httpx2 must be able to send them. |
| `context`, `round_trip`, `serialize_as_any`, `exclude_computed_fields`, `warnings` | Passed to `model_dump` as given. |

```python
from typing import Annotated

from pydantic import BaseModel

from clientx import Body, ClientX, DumpConfig, Response
from clientx.methods import patch


class UserChanges(BaseModel):
    name: str | None = None
    title: str | None = None


class UsersClient(ClientX):
    @patch("/users/{user_id}")
    def update_user(
        self,
        user_id: str,
        changes: Annotated[UserChanges, Body(dump_config=DumpConfig(exclude_unset=True))],
    ) -> Response:
        ...
```

`update_user("42", UserChanges(title=None))` sends the JSON body `{"title": null}`, which clears the title and leaves the name alone.

## Deprecating Endpoints

Use `DeprecatedMessage` for warning-based deprecation:

```python
from clientx import ClientX, DeprecatedMessage, Response
from clientx.methods import get


class LegacyClient(ClientX):
    @get(
        "/v1/legacy",
        deprecated=DeprecatedMessage("Deprecated: use /v2/new-endpoint instead."),
    )
    def legacy(self) -> Response:
        ...
```

You can also pass any callable as `deprecated`, and it will run on endpoint invocation.

## Client Configuration

`ClientX` initializes an internal `httpx2.Client`:

```python
from clientx import ClientX

client = ClientX(
    "https://api.example.com",
    user_agent="MyApp/1.0",
    timeout=5.0,
    headers={"X-Env": "dev"},
)
```

- `user_agent` sets the `User-Agent` header. Without it, a `User-Agent` in `headers=` is kept, or else `ClientX/<version>` is sent.
- Additional kwargs are forwarded to `httpx2.Client(...)`.

### Raising errors for 4xx and 5xx responses

A 4xx or 5xx response raises `httpx2.HTTPStatusError`, from every endpoint, before any decoder runs. The error has the request and the response, and the body is already read, so `exc.response.json()` works:

```python
import httpx2
from pydantic import BaseModel

from clientx import ClientX
from clientx.decoders import ModelDecoder
from clientx.methods import get


class User(BaseModel):
    id: int


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: int) -> User:
        ...


with UsersClient("https://api.example.com") as client:
    try:
        client.get_user(1000)
    except httpx2.HTTPStatusError as exc:
        print(exc.response.status_code, exc.response.json())  # for example: 404 {"error": "not found"}
```

- Redirects aren't errors. With `follow_redirects=True`, only the final response is checked; without it, a 3xx response is returned as it is.
- For a streaming endpoint, an error response is read and closed before the error is raised, so its connection is released. A successful one still streams.
- Endpoints called as AI tools raise it too. Over MCP, it comes back to the model as an error result.

Turn it off for a whole client with `raise_for_status=False`, or set it per endpoint. An endpoint's setting wins over the client's:

```python
from clientx import ClientX, Response
from clientx.methods import get


class FilesClient(ClientX):
    @get("/files/{name}", raise_for_status=False)
    def get_file(self, name: str) -> Response:
        """Return a 404 as a response instead of raising it, so the caller can check `status_code`."""
        ...


client = FilesClient("https://api.example.com")  # every other endpoint still raises
unchecked = FilesClient("https://api.example.com", raise_for_status=False)  # no endpoint raises
```

With the check off, a decoder gets every response, so it can handle error statuses itself.

### Validating arguments

Type checkers catch wrong argument types in your own code, but not in values that arrive at run time, such as user input or data from another service. Turn on `validate_arguments` to check each argument against its parameter's annotation before the request is sent:

```python
from typing import Annotated

from pydantic import Field

from clientx import ClientX, Query, Response
from clientx.exceptions import ArgumentValidationError
from clientx.methods import get


class SearchClient(ClientX):
    @get("/search")
    def search(self, page: Annotated[int, Query(), Field(ge=1)]) -> Response: ...


client = SearchClient("https://api.example.com", validate_arguments=True)

try:
    client.search(0)
except ArgumentValidationError as exc:
    print(exc.parameter)  # page: no request was sent
```

- It's off by default. Turn it on for a whole client with `validate_arguments=True`, or set it per endpoint with the decorators' `validate_arguments=` option. An endpoint's setting wins over the client's.
- The check is strict, like a type checker's: `"1"` doesn't match `int`, and a string doesn't match an `Enum`. Values are never converted, so a request is the same with validation on or off. Constraints in the annotation, such as `Field(ge=1)`, are checked too.
- Only the arguments the caller passes are checked, not defaults.
- A parameter whose type Pydantic can't validate, such as `BinaryIO`, isn't checked. Neither is a parameter without an annotation.
- `ArgumentValidationError` has the `parameter` name and Pydantic's error as `validation_error`. It's a `ClientXError` and a `ValueError`.
- `Tool.call()` already validates a model's arguments, and converts JSON values such as `"red"` to the parameter's type, so tool calls pass this check.

## Logging

ClientX logs one record per endpoint call on the `clientx` logger, at `DEBUG` level, after the response arrives or the request fails:

```
DEBUG:clientx:ClientX request: POST /users/42 -> 201 in 12.3 ms (UsersClient.update_user)
```

To see these records:

```python
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("clientx").setLevel(logging.DEBUG)
```

Each record also has these attributes, for structured log handlers such as JSON formatters:

| Attribute | Example | Meaning |
|---|---|---|
| `clientx_endpoint` | `"UsersClient.update_user"` | The endpoint method. |
| `clientx_method` | `"POST"` | The HTTP method. |
| `clientx_path` | `"/users/42"` | The rendered path, without the query string. |
| `clientx_parts` | `["headers", "json"]` | The names of the request parts sent. |
| `clientx_stream` | `False` | Whether the response is streamed. For a stream, the elapsed time covers the response headers only. |
| `clientx_status` | `201` | The status code, or `None` if no response arrived. |
| `clientx_elapsed_ms` | `12.3` | Time to send the request and receive the response, in milliseconds. |
| `clientx_error` | `None` | The exception's class name if the call failed, such as `"ConnectTimeout"`, or `"HTTPStatusError"` with the status for a 4xx or 5xx response. ClientX re-raises the exception. |

ClientX never logs header values, request bodies, or query strings. The path is logged with its placeholders filled in (`/users/42`), so keep secrets out of path parameters.

httpx2 also logs every request, at `INFO` level on the `httpx2` logger, and its message includes the full URL with the query string. To hide those records, use `logging.getLogger("httpx2").setLevel(logging.WARNING)`.

### Your own request logging

To log requests in your own format or with your own logger, use httpx2's event hooks. ClientX passes `event_hooks` through to `httpx2.Client`:

```python
import logging

import httpx2

from clientx import ClientX

log = logging.getLogger("myapp.http")


def log_request(request: httpx2.Request) -> None:
    log.info("-> %s %s", request.method, request.url.path)


def log_response(response: httpx2.Response) -> None:
    log.info("<- %s %s %s", response.request.method, response.request.url.path, response.status_code)


client = ClientX(
    "https://api.example.com",
    event_hooks={"request": [log_request], "response": [log_response]},
)
```

- Request hooks receive the `httpx2.Request` just before it's sent. Response hooks receive the `httpx2.Response` once its headers arrive, before the body is read.
- Hooks run for every request, including streamed ones. Don't read the body in a response hook: for a streamed endpoint, that would load the whole stream.
- Hooks see everything, including header values and query strings, so redact anything sensitive yourself.
- Hooks don't know which endpoint was called. ClientX's own records do (`clientx_endpoint`), so you can use both.

Deprecated endpoints emit a `DeprecationWarning` through Python's `warnings` module, not a log record. Python hides `DeprecationWarning` by default unless it's triggered by code in `__main__` or under a test runner such as pytest. To send warnings to your logs, call `logging.captureWarnings(True)`; they then appear on the `py.warnings` logger.

## Using a Client from AI Agents

`clientx.tools` describes a client's endpoints as tools for AI models. Each tool gets a name, a description, and JSON Schemas for its arguments and result, built from the method's signature, docstring, and types. `Tool.call` runs a tool with the arguments a model chose, through your client:

```python
from typing import Annotated

from pydantic import BaseModel

from clientx import ClientX, PathParam, Resource
from clientx.decoders import ModelDecoder
from clientx.methods import get
from clientx.tools import list_tools


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @get("/{user_id}", decoder=ModelDecoder(User))
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

`list_tools` takes filters: `read_only=True`, `include_tags=[...]`, `exclude_tags=[...]`, and `include_deprecated=True` (deprecated endpoints are left out by default). Streaming endpoints are always left out, and so is any endpoint whose types have no JSON Schema, such as file uploads, with a warning.

- **Expose only what an agent needs.** Tools can call `POST`, `PUT`, and `DELETE` endpoints. The hints come from the HTTP method, so an API that changes data on `GET` isn't flagged.
- **Keep credentials in the client's configuration** (`auth=`, `headers=`), never in endpoint parameters: parameters become arguments the model sees and fills in.
- `call` validates the arguments before sending anything and raises `pydantic.ValidationError` if they don't match. Request and decoder errors propagate. Most agent loops send the error text back to the model, but an `HTTPStatusError`'s message includes the full URL, query string included: if your client sends credentials as query parameters (`params=`), describe the error from `error.response.status_code` and `error.request.url.path` instead of sending `str(error)`. The MCP server does this for you.

### Serving a client over MCP

With the `mcp` extra, one call turns a client into an [MCP](https://modelcontextprotocol.io) server, so AI apps such as Claude Desktop, Claude Code, and other MCP clients can use your API without any agent code:

```bash
pip install "clientx[mcp]"
```

```python
# server.py
from clientx.mcp import run_mcp_server

from myapp.clients import ExampleAPI

run_mcp_server(ExampleAPI("https://api.example.com", auth=("user", "secret")), read_only=True)
```

Then point your MCP client at the command `python server.py`. In Claude Desktop's `claude_desktop_config.json`, for example:

```json
{"mcpServers": {"example-api": {"command": "python", "args": ["/path/to/server.py"]}}}
```

- The server's tools are exactly the ones `list_tools` returns, with the same names, descriptions, schemas, and filters (`read_only`, `include_tags`, `exclude_tags`, `include_deprecated`). `name=` and `instructions=` set what the server reports to MCP clients.
- The HTTP-method hints become MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), which MCP clients can use to ask for confirmation before changing data.
- Results come back as structured content and as JSON text. Invalid arguments, request failures, and 4xx and 5xx responses come back as error results the model can read, and the server keeps running. A 4xx or 5xx error result has the status, the method and path, and the start of the response body, but never the host or the query string, so credentials in query parameters don't reach the model.
- MCP messages use stdout, so don't print from the server process. Logging writes to stderr by default.
- `run_mcp_server` serves over stdio. For other transports, `create_mcp_server` returns the low-level `mcp.server.lowlevel.Server` to run yourself.

## Error Rules

ClientX raises explicit errors for common contract violations. Most of them are raised when the class is defined, so a broken endpoint fails on import, not on its first call:

- missing return annotation -> `MissingReturnTypeError`
- typed return without decoder -> `MissingDecoderError`
- endpoint or mounted resource named like something `ClientX` already has (`user_agent`, `client`, or a dunder method) -> `EndpointNameConflictError`
- path placeholder, including one from a resource prefix, that names no parameter -> `MissingPathArgumentsError`
- path placeholder with a converter other than `{name:path}` -> `PathTemplateError`
- no positional first parameter for the client (usually `self`, but any name works), a `*args` or `**kwargs` parameter, or a `PathParam()` parameter with no placeholder in the path (including a resource prefix) -> `EndpointSignatureError`
- request-part helper nested inside another type, two helpers on one parameter or field, or `PathParam()` on a model field -> `MisplacedHelperError` (for a model field, when the class is defined if a parameter is annotated with the model, or else when the model is sent)

At call time:

- endpoint called on a resource that isn't mounted on a client -> `UnboundResourceError`
- path value that's `None` or empty, or a `{name:path}` value with a leading, trailing, or doubled slash -> `PathValueError`
- argument cannot map to request parts, or a model field marked `Body()` or `File()` holds something other than a mapping or a model -> `UnconsumableArgumentError`
- argument doesn't match its annotation, when `validate_arguments` is on -> `ArgumentValidationError`

Annotations are evaluated when the class is defined, so endpoints work in modules with `from __future__ import annotations`. Like `pydantic`, ClientX evaluates them against the module's globals: a type defined inside a function can't be named in a string annotation.

All of them derive from `ClientXError` (importable from `clientx`), so `except ClientXError` catches any of them. Each also keeps its built-in base (`TypeError` or `ValueError`).

HTTP errors come from httpx2: connection errors and timeouts, and `HTTPStatusError` for 4xx and 5xx responses unless it's turned off (see [Raising errors for 4xx and 5xx responses](#raising-errors-for-4xx-and-5xx-responses)).

## Development

See [CONTRIBUTING.md](https://github.com/slatecipher/ClientX/blob/mainline/CONTRIBUTING.md) for setup, checks, and conventions.
