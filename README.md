# ClientX

Typed, declarative HTTP API clients for Python 3.12+.

## Overview

ClientX is a declarative API client framework designed to make writing and maintaining API clients easier while keeping the client contract explicit and well documented.

For client authors, ClientX reduces boilerplate by turning typed endpoint definitions into concrete `httpx2` requests and centralizing request/response behavior. For client consumers, it pushes API contracts and guard rails into the client itself, helping prevent avoidable runtime mistakes and making integrations more predictable.

The result is less scaffolding code and more focus on outcomes: authors spend less time on plumbing, and consumers spend less time guessing how to call your API correctly.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Typed response handling with pluggable decoders.
- Path parameter rendering from method arguments (e.g. `"/users/{user_id}"`).
- Request payload mapping from parameter names, `Annotated` metadata, or Pydantic models.
- Built-in deprecation warnings per endpoint.
- Endpoint metadata tags for registry filtering and sorting.
- Full access to `httpx2.Client` configuration through `ClientX(...)` kwargs.

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
- `tags` (optional list of metadata labels for registry tooling)

```python
from clientx import ClientX, Response
from clientx.methods import post


class ItemsClient(ClientX):
    @post("/items")
    def create_item(self, json: dict[str, object]) -> Response:
        ...
```

## Endpoint Registry (`EndpointRegister`)

`EndpointRegister` is a developer-facing introspection tool that collects decorated endpoints at import time. It is useful when you want to build metadata-driven tooling around your client classes.

Common uses:

- Generate JSON metadata files describing methods, paths, return types, and deprecation status.
- Feed endpoint metadata into documentation generators.
- Build context for internal systems (for example validation, tracing, SDK tooling, or contract checks).
- Filter or sort endpoints by custom tags (for example domain, stability, or ownership).

```python
from clientx import EndpointRegister

for endpoint in EndpointRegister.iter():
    print(endpoint.method, str(endpoint.path), endpoint.return_type)

public_endpoints = [endpoint for endpoint in EndpointRegister.iter() if "public" in endpoint.tags]
for endpoint in sorted(public_endpoints, key=lambda item: (item.method, str(item.path))):
    print(endpoint.method, str(endpoint.path), endpoint.tags)
```

You can attach tags directly in the endpoint decorator:

```python
from clientx import ClientX, Response
from clientx.methods import get


class UsersClient(ClientX):
    @get("/users", tags=["public", "users"])
    def list_users(self) -> Response:
        ...
```

## Return Types and Decoders

ClientX enforces explicit return annotations:

- `-> Response`: returns raw `httpx2.Response`.
- `-> None`: sends request and returns `None`.
- Any other type: requires `decoder=...`.

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

`ClientX` initializes an internal `httpx2.Client`:

```python
ClientX(
    "https://api.example.com",
    user_agent="MyApp/1.0",
    timeout=5.0,
    headers={"X-Env": "dev"},
)
```

- `user_agent` defaults to `ClientX/<version>`.
- Additional kwargs are forwarded to `httpx2.Client(...)`.

## Error Rules

ClientX raises explicit errors for common contract violations:

- missing return annotation -> `MissingReturnTypeError`
- typed return without decoder -> `MissingDecoderError`
- path placeholders not provided -> `MissingPathArgumentsError`
- argument cannot map to request parts -> `UnconsumableArgumentError`

All of them derive from `ClientXError` (importable from `clientx`), so `except ClientXError` catches any of them. Each also keeps its built-in base (`TypeError` or `ValueError`).

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
