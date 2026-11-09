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
- **Built on httpx2.** Every `httpx2.Client` option is available, including auth, timeouts, proxies, and custom transports, and responses can be streamed.

ClientX is an independent project. It isn't affiliated with or endorsed by the FastAPI, Pydantic, or httpx2 projects.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Typed response handling with pluggable decoders.
- Path parameter rendering from method arguments (e.g. `"/users/{user_id}"`).
- Request payload mapping from parameter names, `Annotated` metadata, or Pydantic models.
- Built-in deprecation warnings per endpoint.
- Endpoint metadata tags for registry filtering and sorting.
- Full access to `httpx2.Client` configuration through `ClientX(...)` kwargs.

## Project status

ClientX is a personal project that I maintain in my spare time. Issues and pull requests are welcome, but replies may take a while, and there is no guaranteed response time.

ClientX is pre-1.0, so the API may change between minor versions. Changes are listed in the [changelog](https://github.com/slatecipher/ClientX/blob/mainline/CHANGELOG.md).

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
- `timeout` (optional per-endpoint `httpx2.Timeout` or seconds)

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

If you pass a decoder, it always runs and its output is returned, whatever the annotation. For example, a decoder can call `response.raise_for_status()` on a `-> Response` or `-> None` endpoint.

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

1. Path placeholders (e.g. `{user_id}`) are consumed from arguments.
2. Each remaining argument goes to the first of these that matches:
   1. Its name is a request part: `json`, `params`, `data`, `files`, or `headers`. The name wins even over a `FieldX` annotation, so a parameter named `data` is always sent as form data.
   2. `Annotated[..., FieldX(RequestPart.*)]`.
   3. Its value is a Pydantic model, which is expanded field by field.

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

`FieldX` sends a parameter to a specific request part. To send a single value as a query parameter, header, or form field, set `key` to the name it should be sent under. The key can differ from the Python parameter name:

```python
from enum import Enum
from typing import Annotated

from clientx import ClientX, FieldX, RequestPart, Response
from clientx.methods import get, post


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class ItemsClient(ClientX):
    @get("/items")
    def list_items(
        self,
        item_type: Annotated[str, FieldX(RequestPart.PARAMS, key="type")],
        sort: Annotated[Sort, FieldX(RequestPart.PARAMS, key="sort")] = Sort.NEWEST,
    ) -> Response:
        ...

    @post("/items")
    def create_item(
        self,
        token: Annotated[str, FieldX(RequestPart.HEADERS, key="Authorization")],
        payload: Annotated[dict[str, object], FieldX(RequestPart.JSON)],
    ) -> Response:
        ...
```

`list_items("book", Sort.OLDEST)` sends `GET /items?type=book&sort=oldest`.

- `key` works with `PARAMS`, `HEADERS`, and `DATA`. The value is sent as `{key: value}`, and an `Enum` member is sent as its `.value`.
- Without `key`, the value must already be a mapping, such as `dict[str, str]`. A single string or number fails when the request is built.
- `key` is ignored for `JSON` and `FILES`, which send the value as given.
- `key` only works on method parameters. Inside a Pydantic model, fields routed to a request part must be mappings (see below).

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
        payload: Annotated[
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
from clientx import ClientX

client = ClientX(
    "https://api.example.com",
    user_agent="MyApp/1.0",
    timeout=5.0,
    headers={"X-Env": "dev"},
)
```

- `user_agent` defaults to `ClientX/<version>`.
- Additional kwargs are forwarded to `httpx2.Client(...)`.

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
| `clientx_status` | `201` | The status code, or `None` if the request failed. |
| `clientx_elapsed_ms` | `12.3` | Time to send the request and receive the response, in milliseconds. |
| `clientx_error` | `None` | The exception's class name if the request failed, such as `"ConnectTimeout"`. ClientX re-raises the exception. |

ClientX never logs values: no header values, request bodies, or query strings.

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

## Error Rules

ClientX raises explicit errors for common contract violations:

- missing return annotation -> `MissingReturnTypeError`
- typed return without decoder -> `MissingDecoderError`
- endpoint method named like something `ClientX` already has (`send`, `user_agent`, `client`, or a dunder method) -> `EndpointNameConflictError`
- path placeholders not provided -> `MissingPathArgumentsError`
- argument cannot map to request parts -> `UnconsumableArgumentError`

All of them derive from `ClientXError` (importable from `clientx`), so `except ClientXError` catches any of them. Each also keeps its built-in base (`TypeError` or `ValueError`).

## Development

See [CONTRIBUTING.md](https://github.com/slatecipher/ClientX/blob/mainline/CONTRIBUTING.md) for setup, checks, and conventions.
