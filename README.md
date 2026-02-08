# ClientX

Typed, declarative HTTP API clients for Python 3.12+.

## Overview

ClientX is a declarative API client framework designed to make writing and maintaining API clients easier while keeping the client contract explicit and well documented.

For client authors, ClientX reduces boilerplate by turning typed endpoint definitions into concrete `httpx` requests and centralizing request/response behavior. For client consumers, it pushes API contracts and guard rails into the client itself, helping prevent avoidable runtime mistakes and making integrations more predictable.

The result is less scaffolding code and more focus on outcomes: authors spend less time on plumbing, and consumers spend less time guessing how to call an API correctly.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Typed response handling with pluggable decoders.
- Path parameter rendering from method arguments (e.g. `"/users/{user_id}"`).
- Request payload mapping from parameter names, `Annotated` metadata, or Pydantic models.
- Built-in deprecation warnings per endpoint.
- Full access to `httpx.Client` configuration through `ClientX(...)` kwargs.

## Install

```bash
pip install clientx
```

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

- `path` (required)
- `decoder` (required when return type is not `Response` or `None`)
- `deprecated` (optional callable, including `DeprecatedMessage`)

```python
from clientx import ClientX, Response
from clientx.methods import post


class ItemsClient(ClientX):
    @post("/items")
    def create_item(self, json: dict[str, object]) -> Response:
        ...
```

## Return Types and Decoders

ClientX enforces explicit return annotations:

- `-> Response`: returns raw `httpx.Response`.
- `-> None`: sends request and returns `None`.
- Any other type: requires `decoder=...`.

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
from httpx import Response
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

## Building Request Payloads

ClientX maps method arguments into request parts in this order:

1. Path placeholders (e.g. `{user_id}`) are consumed from arguments.
2. Remaining arguments map to request parts via one of:
   - parameter name equals a request part: `json`, `params`, `data`, `files`, `headers`
   - `Annotated[..., FieldX(RequestPart.*)]`
   - Pydantic model expansion

### By parameter name

```python
from clientx import ClientX, Response
from clientx.methods import get


class SearchClient(ClientX):
    @get("/search")
    def search(self, params: dict[str, object], headers: dict[str, str]) -> Response:
        ...
```

### By `Annotated` + `FieldX`

```python
from typing import Annotated

from clientx import ClientX, FieldX, RequestPart, Response
from clientx.methods import post


class UploadClient(ClientX):
    @post("/upload")
    def upload(
        self,
        auth: Annotated[str, FieldX(RequestPart.HEADERS)],
        payload: Annotated[dict[str, object], FieldX(RequestPart.JSON)],
    ) -> Response:
        ...
```

### By Pydantic model

```python
from typing import Annotated

from pydantic import BaseModel

from clientx import ClientX, FieldX, RequestPart, Response
from clientx.methods import post


class CreateUserPayload(BaseModel):
    headers: Annotated[dict[str, str], FieldX(RequestPart.HEADERS)]
    params: Annotated[dict[str, str], FieldX(RequestPart.PARAMS)]
    name: str
    email: str


class UsersClient(ClientX):
    @post("/users")
    def create_user(self, payload: CreateUserPayload) -> Response:
        ...
```

In model extraction, fields explicitly routed to `HEADERS`, `PARAMS`, `DATA`, or `FILES` should be mappings. Unassigned fields default to JSON.

### Serialization control with `DumpConfig`

```python
from typing import Annotated

from pydantic import BaseModel

from clientx import ClientX, DumpConfig, FieldX, RequestPart, Response
from clientx.methods import post


class PatchPayload(BaseModel):
    name: str | None = None
    title: str | None = None


class UsersClient(ClientX):
    @post("/users/{user_id}")
    def patch_user(
        self,
        user_id: str,
        data: Annotated[
            PatchPayload,
            FieldX(RequestPart.JSON, dump_config=DumpConfig(exclude_none=True)),
        ],
    ) -> Response:
        ...
```

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

`ClientX` initializes an internal `httpx.Client`:

```python
ClientX(
    "https://api.example.com",
    user_agent="MyApp/1.0",
    timeout=5.0,
    headers={"X-Env": "dev"},
)
```

- `user_agent` defaults to `ClientX/<version>`.
- Additional kwargs are forwarded to `httpx.Client(...)`.

## Error Rules

ClientX raises explicit errors for common contract violations:

- missing return annotation -> `MissingReturnTypeError`
- typed return without decoder -> `MissingDecoderError`
- path placeholders not provided -> `MissingPathArgumentsError`
- argument cannot map to request parts -> `UnconsumableArgumentError`

## Development

```bash
make lint
make test
```

or directly:

```bash
uv run ruff format src test
uv run ruff check --fix src test
uv run pytest
```
