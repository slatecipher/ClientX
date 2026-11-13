# Return Types and Decoders

ClientX enforces explicit return annotations:

- `-> Response`: returns raw `httpx2.Response`. `clientx.Response` is the same class: `clientx` re-exports it from httpx2, along with `Auth`, `Request`, and `Timeout`, so a client module doesn't need to import httpx2 for them.
- `-> None`: sends request and returns `None`.
- Any other type: requires `decoder=...`.

A 4xx or 5xx response raises `httpx2.HTTPStatusError` before any decoder runs (see [Raising errors for 4xx and 5xx responses](configuration.md#raising-errors-for-4xx-and-5xx-responses)). Otherwise, if you pass a decoder, it always runs and its output is returned, whatever the annotation. If the decoder raises, its exception reaches the caller unchanged. `ModelDecoder`, `TypeAdapterDecoder`, and `json_decoder` raise `ValueError` subclasses, so `except ValueError` catches all of them: `pydantic.ValidationError` when the body doesn't match the type, `json.JSONDecodeError` when it isn't JSON, and a plain `ValueError` when `TypeAdapterDecoder`'s `key` is missing. The request itself succeeded, so its [log record](logging.md) shows the response's status and no error.

A decoder is a callable that receives the raw `httpx2.Response` and returns the value that matches your method's return annotation. ClientX executes the HTTP request first, then passes the response into the decoder, and returns the decoder output to the caller.

Type checkers enforce the match: a method annotated with anything other than `Response` or `None` that has no decoder is reported as an error, and so is `decoder=ModelDecoder(User)` on a method annotated `-> str`. Both errors point at the decorator:

- No decoder, on `def get_user(self, user_id: int) -> User`:
  - pyright: `Type "User" is not assignable to constrained type variable "ResponseOrNone"`
  - mypy: `Value of type variable "ResponseOrNone" of "__call__" of "RawEndpointDecorator" cannot be "User"  [type-var]`

  Add a decoder, such as `decoder=ModelDecoder(User)`, or return `Response` or `None`.
- A decoder that doesn't match, `decoder=ModelDecoder(User)` on `-> str`:
  - pyright: `Function return type "str" is incompatible with type "User"`
  - mypy: `Argument 1 to "__call__" of "DecodedEndpointDecorator" has incompatible type "Callable[[UsersClient, int], str]"; expected "Callable[[UsersClient, int], User]"  [arg-type]`

  Make the return annotation match the decoder's output. mypy also notes that the method "has named arguments" and suggests marking them positional-only; that's its generic hint for callable mismatches, and doesn't apply here.

The decorators take `def` and `async def` methods, so pyright also reports `No overloads for "__call__" match the provided arguments` at the decorator. For an `async def` method, the messages name its coroutine type instead: `Coroutine[Any, Any, User]` in mypy, and `CoroutineType[Any, Any, User]` in pyright.

In practice, decoders are where you define response parsing and validation behavior:

- Parse JSON/text/bytes from the response body.
- Validate and coerce payloads into typed Python objects.
- Build richer return objects that combine body data with headers/status metadata.

## `ModelDecoder`

```python
from clientx import ClientX
from clientx.decoders import ModelDecoder
from clientx.methods import get
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: str) -> User:
        ...
```

## `TypeAdapterDecoder`

```python
from clientx import ClientX
from clientx.decoders import TypeAdapterDecoder
from clientx.methods import get
from pydantic import TypeAdapter

UserList = TypeAdapter(list[dict[str, str]])


class UsersClient(ClientX):
    @get("/users", decoder=TypeAdapterDecoder(UserList))
    def list_users(self) -> list[dict[str, str]]:
        ...
```

`TypeAdapterDecoder` takes a `TypeAdapter`, not a bare type. For an API that wraps its data in an object, `key=` validates one member instead of the whole body: `TypeAdapterDecoder(TypeAdapter(list[User]), key="results")` decodes `{"count": 2, "results": [...]}` into a `list[User]`. A body that isn't a JSON object with that key raises `ValueError`, such as `TypeAdapterDecoder(key='results') expected a JSON object with a 'results' key, but the response body is an array.`

## `FromResponseDecoder`

```python
from clientx import ClientX
from clientx.decoders import FromResponseDecoder
from clientx.methods import get
from httpx2 import Response
from pydantic import BaseModel


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

## Vanilla decoders (`clientx.decoders`)

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

## Bring Your Own Decoder (BYOD)

You can pass any callable with signature `(response: httpx2.Response) -> T` as `decoder=...`. Type checkers require `T` to match your endpoint's return annotation.

Use BYOD when you need behavior that is specific to your API contract, such as envelope unwrapping, fallback parsing, or custom validation rules.

```python
from clientx import ClientX
from clientx.methods import get
from httpx2 import Response
from pydantic import BaseModel, TypeAdapter


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

## Streaming responses

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

- `StreamLinesDecoder` yields text lines, and `StreamChunksDecoder(chunk_size=...)` yields byte chunks. To write your own, subclass `StreamDecoder`. For `async def` endpoints, use the async stream decoders (see [Async clients](async.md#streaming)).
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
