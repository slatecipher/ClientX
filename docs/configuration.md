# Client Configuration

Configure a client when you create it:

<!-- docs_src/configuration/creating.py -->
```python
from clientx import ClientX


class ExampleAPI(ClientX): ...


api = ExampleAPI("https://api.example.com", user_agent="my-app/1.0", timeout=5.0)
```

- `base_url`: the API's base URL, which every endpoint's path is relative to. It's required unless the class sets one (see [Class defaults](#class-defaults)), and it wins over the class's.
- `user_agent`: the `User-Agent` to send. Without it, the first of these is sent: a `User-Agent` in `headers=`, the class's `user_agent=` (see [Class defaults](#class-defaults)), or `ClientX/<version>`.
- `raise_for_status`: whether a 4xx or 5xx response raises `httpx2.HTTPStatusError`. It's on by default; see [Errors for 4xx and 5xx responses](responses.md#errors-for-4xx-and-5xx-responses).
- `validate_arguments`: whether each call's arguments are checked against their annotations before anything is sent. It's off by default; see [Validating arguments](#validating-arguments).
- Any other `httpx2.Client` option, such as `timeout`, `headers`, `params`, `auth` (see [Authentication](#authentication)), `transport`, `proxy` or `follow_redirects`.

A `ClientX` is an `httpx2.Client`, so those options, and everything else httpx2 documents for a client, work as they do there. That includes changing `headers`, `params`, `auth` or `timeout` on a client after it's created: the change applies to every endpoint. Each client has its own connections, settings and credentials, so clients for production and staging, or one per account, can be used side by side.

A client's `repr` shows its class, its base URL and its `User-Agent`, with any password in the base URL replaced by `[redacted]`: `ExampleAPI(base_url='https://api.example.com', user_agent='my-app/1.0')`.

For `async def` endpoints, `AsyncClientX` takes the same arguments and class arguments (see [Async clients](async.md)).

## Class defaults

A client class can set the base URL and the `User-Agent` its clients use, as class arguments:

<!-- docs_src/configuration/class_defaults.py -->
```python
from clientx import ClientX


class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-api/1.0"): ...


api = ExampleAPI()  # https://api.example.com, User-Agent: example-api/1.0
staging = ExampleAPI("https://staging.example.com")
```

A subclass keeps its parent's class arguments unless it sets its own, and a `base_url` or `user_agent` given when creating a client wins over the class's.

- A client needs a base URL from one or the other. Without either, creating it raises `TypeError`, as a missing argument does. Type checkers can't see whether a class sets one, so they don't catch this.
- A base URL must be absolute, with a scheme and a host, such as `https://api.example.com`, since httpx2 would take `api.example.com` alone as a relative path and fail only on the first request. A class's raises `DefinitionError` when the class is defined, and one passed when creating a client raises `ValueError`.

`base_url` and `user_agent` are the only class arguments. Pass every other option when creating the client: Python rejects any other keyword in the class statement, a misspelling included, with `TypeError: ExampleAPI.__init_subclass__() takes no keyword arguments`.

## Validating arguments

ClientX sends arguments as they're passed: type checkers catch a wrong type in code they check, and a helper's constraints, such as `Query(ge=1)`, aren't checked. To check each call's arguments against their annotations before anything is sent, create the client with `validate_arguments=True`:

<!-- docs_src/configuration/validating_arguments.py -->
```python
from typing import Annotated

from clientx import ArgumentError, ClientX, Query, method


class ExampleAPI(ClientX, base_url="https://api.example.com"):
    @method.get("/users")
    def list_users(self, page: Annotated[int, Query(ge=1)] = 1) -> None: ...


with ExampleAPI(validate_arguments=True) as api:
    try:
        api.list_users(page=0)
    except ArgumentError as error:
        print(error.parameter)  # page: no request was sent
```

- Arguments are checked strictly, as a type checker would: `"7"` doesn't fit an `int`. A helper's constraints are checked too.
- Only the arguments a call passes are checked, not the defaults.
- The request is built from the arguments as they were passed: checking never changes what's sent. A model instance isn't validated again.
- A parameter whose type Pydantic can't validate isn't checked: a binary file (`IO[bytes]`, `BinaryIO`, or a file tuple holding one), `Iterator[bytes]` or an async stream, or your own class that Pydantic doesn't know. A stream's items are never checked. Pydantic's [Standard Library Types](https://pydantic.dev/docs/validation/latest/api/pydantic/standard_library_types/) lists what it validates, and how strictly.
- An argument that doesn't fit raises [`ArgumentError`](errors.md#argumenterror). Its `parameter` names the first one that doesn't fit, its message lists every problem, and Pydantic's `ValidationError` is its `__cause__`.
- It's for the whole client, and off unless you turn it on: in tests, for example, or for callers whose code isn't type-checked.

## Authentication

Give a client its credentials with `auth=` when you create it. `auth=` is httpx2's authentication option: the client applies it to every request. For what it accepts and how to write your own scheme, see httpx2's [Authentication](https://pydantic.dev/docs/httpx2/advanced/authentication/) documentation.

Keep credentials out of endpoint parameters: every caller would have to pass them.

Don't add credentials in a request [event hook](#logging-and-event-hooks). httpx2 documents hooks for logging, monitoring and tracing. A request hook also runs again for every redirect, so it would put back an `Authorization` header that httpx2 dropped for another host. And it can't send a token request through the client's flow or send a request again after a 401.

For other schemes, httpx2's [Third Party Packages](https://pydantic.dev/docs/httpx2/community/third_party_packages/) page lists libraries that support it. Use a library's `Auth` class as `auth=`, not its client class.

## Closing a client

Close a client when you're done with it, to release its connections:

- For a script or one batch of calls, use a `with` block. It closes the client when the block ends, even if an exception is raised.
- For a long-lived client, such as one in a web app or a worker, create it once, reuse it for every request so its connections are pooled, and call `close()` at shutdown. Don't create a client for each request.
- A closed client can't be reused: a call raises `RuntimeError: Cannot send a request, as the client has been closed.` Create a new one.
- An `AsyncClientX` closes the same way, with `async with` or `await client.aclose()`.
- `with` is optional. A client that's never closed still works; its connections stay open until the process exits or the client is garbage-collected.

## Logging and event hooks

ClientX doesn't log anything itself. httpx2 logs every request at `INFO` level on the `httpx2` logger:

```
INFO:httpx2:HTTP Request: GET https://api.example.com/users/42 "HTTP/1.1 200 OK"
```

The message includes the full URL, query string included, so values in `params=` appear in your logs whenever that logger is on. That's one more reason to keep credentials in `auth=`. To hide these records, use `logging.getLogger("httpx2").setLevel(logging.WARNING)`.

To log requests in your own format, or with your own logger, use httpx2's event hooks, which a client takes as `event_hooks=`:

<!-- docs_src/configuration/event_hooks.py -->
```python
import logging

import httpx2
from clientx import ClientX

log = logging.getLogger("myapp.http")


def log_request(request: httpx2.Request) -> None:
    log.info("-> %s %s", request.method, request.url.path)


def log_response(response: httpx2.Response) -> None:
    log.info("<- %s %s %s", response.request.method, response.request.url.path, response.status_code)


class ExampleAPI(ClientX): ...


api = ExampleAPI(
    "https://api.example.com",
    event_hooks={"request": [log_request], "response": [log_response]},
)
```

- Request hooks receive the `httpx2.Request` just before it's sent. Response hooks receive the `httpx2.Response` once its headers arrive, before the body is read.
- Hooks run for every request, including streamed ones. Don't read the body in a response hook: for a streaming endpoint, that would load the whole stream.
- Hooks see everything, including header values and query strings, so redact anything sensitive yourself.
- An `AsyncClientX`'s hooks must be `async` functions. See httpx2's [Event Hooks](https://pydantic.dev/docs/httpx2/advanced/event-hooks/) documentation for more.
