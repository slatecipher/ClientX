# Responses

> [!IMPORTANT]
> By default, every endpoint raises `httpx2.HTTPStatusError` for a 4xx or 5xx response, before anything is decoded. See [Errors for 4xx and 5xx responses](#errors-for-4xx-and-5xx-responses) for what the error holds, and how to turn the check off for a client or an endpoint.

An endpoint's return annotation decides what it returns:

| Annotation | Returns |
|---|---|
| `-> None` | nothing |
| `-> Response` | the `httpx2.Response`, with its body already read |
| `-> str` | the body as text |
| `-> bytes` | the body as bytes |
| `-> Iterator[str]` | the body, streamed line by line (see [Streaming](#streaming)) |
| `-> Iterator[bytes]` | the body, streamed in chunks |
| any other type | the JSON body, validated against the annotation (see [Typed results](#typed-results)) |

`clientx.Response` is `httpx2.Response`: `clientx` re-exports it from httpx2, along with `Auth`, `Request` and `Timeout`, so a client module doesn't need to import httpx2 for them.

## Typed results

For any annotation not in the table above (`None`, `Response`, `str`, `bytes`, or a stream), Pydantic validates the JSON body against the full annotation, so a model, a `list[User]`, a `dict[str, int]`, a dataclass, a `TypedDict` or a union all work, and so do constraints in `Annotated`:

<!-- docs_src/responses/typed_results.py -->
```python
from typing import Annotated

from clientx import ClientX, method
from pydantic import BaseModel, Field


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...

    @method.get("/users")
    def list_users(self) -> list[User]: ...

    @method.get("/users/count")
    def count_users(self) -> Annotated[int, Field(ge=0)]: ...
```

- A body that doesn't match the annotation, or isn't JSON, raises `pydantic.ValidationError`, which is a `ValueError`.
- The validator is built when the class is defined, so a type Pydantic can't validate, such as `BinaryIO`, raises `DefinitionError` then, naming the type.
- For an API that wraps its data, such as `{"count": 2, "results": [...]}`, annotate a model of the wrapper, or pass a [decoder](#your-own-decoder) that returns the part you want.

## Streaming

`-> Iterator[str]` streams the body as text lines, and `-> Iterator[bytes]` as chunks of bytes, so a large or endless body is never held in memory. For an `async def` endpoint, annotate `-> AsyncIterator[str]` or `-> AsyncIterator[bytes]` instead (see [Async clients](async.md#streaming)).

<!-- docs_src/responses/streaming.py -->
```python
from collections.abc import Iterator

from clientx import ClientX, method


class LogsAPI(ClientX):
    @method.get("/jobs/{job_id}/log")
    def follow_log(self, job_id: str) -> Iterator[str]: ...


with LogsAPI("https://api.example.com") as api:
    for line in api.follow_log("build-42"):
        print(line)
```

- Calling the endpoint sends the request, and raises for a 4xx or 5xx response, before it returns the iterator.
- The response is closed when iteration finishes, when the loop exits early (`break` or an exception), or when you call `.close()` on the iterator. An iterator that's never started, or that you keep partly consumed, holds its connection until it's closed or garbage-collected.
- To stream anything other than text lines or bytes, such as a model per line, pass a [generator decoder](#your-own-decoder). An annotation such as `-> Iterator[Event]` without one raises `DefinitionError`.

## The open response

With `stream=True`, an endpoint annotated `-> Response` returns the open, unread response, and you decide how to read it. You own it, so close it when you're done:

<!-- docs_src/responses/open_response.py -->
```python
from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{file_id}", stream=True)
    def download(self, file_id: str) -> Response: ...


with FilesAPI("https://api.example.com") as api:
    response = api.download("42")
    try:
        with open("file.bin", "wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    finally:
        response.close()
```

`stream=True` needs `-> Response` and no `decoder=`; anything else raises `DefinitionError`. A 4xx or 5xx response still raises, after it's read and closed.

## Your own decoder

`decoder=` takes any function that turns the `httpx2.Response` into the value the endpoint returns, in place of the decoding its annotation implies:

<!-- docs_src/responses/decoder.py -->
```python
from clientx import ClientX, Response, method
from pydantic import BaseModel, TypeAdapter


class Item(BaseModel):
    id: int
    name: str


ITEMS = TypeAdapter(list[Item])


def items_in_envelope(response: Response) -> list[Item]:
    """Read the items from a body such as {"data": {"items": [...]}}."""
    return ITEMS.validate_python(response.json()["data"]["items"])


class ItemsAPI(ClientX):
    @method.get("/items", decoder=items_in_envelope)
    def list_items(self) -> list[Item]: ...
```

- The body is already read when the decoder runs, so it can use `response.json()`, `response.text`, the headers and the status code.
- The decoder does the validating, and ClientX returns its result as is. Building a model, as in `User.model_validate(response.json())`, or using a `TypeAdapter`, as `items_in_envelope` does, validates the data as Pydantic always does. A decoder that returns `response.json()` unchanged returns an unvalidated `dict`.
- Type checkers check that the decoder's declared return type matches the annotation, and report a mismatch at the decorator.
- A decoder is a plain function, or any callable object, that takes the `Response`. It's plain even for an `async def` endpoint, since the body is read before it runs: an `async def` decoder raises `DefinitionError`. So does a decoder on an endpoint annotated `-> None`.
- An exception the decoder raises reaches the caller unchanged.

A generator decoder streams. On an endpoint annotated `-> Iterator[...]`, it gets the response unread and yields the items as it reads them:

<!-- docs_src/responses/generator_decoder.py -->
```python
from collections.abc import Iterator

from clientx import ClientX, Response, method
from pydantic import BaseModel


class Event(BaseModel):
    id: int
    kind: str


def parse_events(response: Response) -> Iterator[Event]:
    """Yield an event for each line of JSON."""
    for line in response.iter_lines():
        if line:
            yield Event.model_validate_json(line)


class EventsAPI(ClientX):
    @method.get("/events", decoder=parse_events)
    def watch(self) -> Iterator[Event]: ...
```

The response, and the generator, are closed when iteration ends, as for any stream. For an `async def` endpoint annotated `-> AsyncIterator[...]`, the decoder is an async generator (see [Async clients](async.md#streaming)). A generator decoder of the other kind, or one on an endpoint that isn't annotated as a stream, raises `DefinitionError`.

## Errors for 4xx and 5xx responses

By default, a 4xx or 5xx response raises `httpx2.HTTPStatusError` from every endpoint, before anything is decoded. A plain httpx2 client leaves that to you, with `response.raise_for_status()`. The error has the request and the response, and the body is already read, so `error.response.json()` works:

<!-- docs_src/responses/status_errors.py -->
```python
import httpx2
from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...


with UsersAPI("https://api.example.com") as api:
    try:
        api.get_user(1000)
    except httpx2.HTTPStatusError as error:
        print(error.response.status_code, error.response.json())  # for example: 404 {'detail': 'Not found'}
```

- A redirect isn't an error, and httpx2 follows one only with the client's `follow_redirects=True`. Without it, the redirect response itself is decoded, which fails for a typed result; with it, only the final response is checked.
- For a streaming endpoint, an error response is read and closed before the error is raised, so its connection is released. A successful one still streams.

Turn it off for a whole client with `raise_for_status=False`, or set it for one endpoint. An endpoint's setting wins over the client's:

<!-- docs_src/responses/raise_for_status.py -->
```python
from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{name}", raise_for_status=False)
    def get_file(self, name: str) -> Response:
        """Return a 404 as a response instead of raising, so the caller can check `status_code`."""
        ...


api = FilesAPI("https://api.example.com")  # every other endpoint still raises
unchecked = FilesAPI("https://api.example.com", raise_for_status=False)  # no endpoint raises
```

With the check off, an error response is decoded like any other, so annotate the endpoint `-> Response`, or pass a decoder that handles error statuses.
