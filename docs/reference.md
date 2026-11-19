# API Reference

Everything public in ClientX is on this page. Import it from `clientx`, use the verb decorators through `clientx.method` (`from clientx import method`, then `@method.get(...)`), and import the AI tools from `clientx.tools`. The submodules `clientx.arguments` and `clientx.exceptions` hold names that `clientx` already exports, so either import works.

Anything else is internal and can change in any release: modules whose names start with an underscore, such as `clientx._planner`, and any name not listed here. ClientX is pre-1.0, so the public API can change between minor versions too. The [changelog](../CHANGELOG.md) lists each change.

| Name | What it is |
|---|---|
| [`ClientX`](#clientx), [`AsyncClientX`](#asyncclientx) | The base classes for a client. |
| [`Resource`](#resource), [`AsyncResource`](#asyncresource) | The base classes for a group of endpoints under a path prefix. |
| [`method`](#method) | The verb decorators: `get`, `post`, `put`, `patch`, `delete`, `head` and `options`. |
| [`Url`, `Query`, `Header`, `Json`, `Body`, `Form`, `File`](#request-helpers) | The request helpers, which say where a parameter goes. |
| [`Send`](#send) | Options that change how a parameter is sent. |
| [`ClientXError`, `DefinitionError`, `ArgumentError`](#errors) | The errors ClientX raises. |
| [`Auth`, `Request`, `Response`, `Timeout`](#from-httpx2) | httpx2's own classes, re-exported. |
| [`list_tools`, `Tool`, `ToolError`](#clientxtools) | From `clientx.tools`: a client's endpoints as tools a model can call. |
| [`__version__`](#__version__) | The installed version. |

## `ClientX`

```py
class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example/1.0"):
    ...  # endpoints, mounted resources and plain methods


ExampleAPI(
    base_url: str | httpx2.URL | None = None,
    *,
    user_agent: str | None = None,
    raise_for_status: bool | None = None,
    **options,  # any httpx2.Client option
)
```

The base class for a client. Subclass it, and declare each endpoint as a `def` method with an empty body and a [verb decorator](#method). A `ClientX` is an [`httpx2.Client`](https://pydantic.dev/docs/httpx2/api/#httpx2.Client), so it's configured, used and closed like one: in a `with` block, or with `close()`.

Class arguments, in the class statement:

| Argument | Type | Default | Effect |
|---|---|---|---|
| `base_url` | `str` or `httpx2.URL` | none | The base URL a client uses when it's created without one. It must be absolute, with a scheme and a host, or the class raises `DefinitionError`. |
| `user_agent` | `str` | `ClientX/<version>` | The `User-Agent` a client sends when it's created without one. |

A subclass keeps its parent's class arguments unless it sets its own. Any other keyword in the class statement raises `TypeError`.

Arguments when creating a client:

| Argument | Type | Default | Effect |
|---|---|---|---|
| `base_url` | `str` or `httpx2.URL` | the class's | The URL every endpoint's path is relative to. With none here or on the class, creating the client raises `TypeError`, and one that isn't absolute raises `ValueError`. |
| `user_agent` | `str` | a `User-Agent` in `headers=`, else the class's | The `User-Agent` to send. |
| `raise_for_status` | `bool` | `True` | Whether a 4xx or 5xx response raises `httpx2.HTTPStatusError`. An endpoint's own `raise_for_status=` wins. |
| `**options` | | | Any [`httpx2.Client` option](https://pydantic.dev/docs/httpx2/api/#httpx2.Client), such as `auth`, `headers`, `params`, `cookies`, `timeout`, `verify`, `proxy`, `transport`, `mounts`, `event_hooks` or `follow_redirects`. |

An endpoint or mounted resource on a client can't use a name the client already has, which includes every name of `httpx2.Client`, such as `get` or `send` (see [Endpoint names](endpoints.md#endpoint-names)). The client's own httpx2 methods still send one-off requests. See [Client configuration](configuration.md).

## `AsyncClientX`

```py
class ExampleAPI(AsyncClientX, base_url="https://api.example.com", user_agent="example/1.0"):
    ...


ExampleAPI(
    base_url: str | httpx2.URL | None = None,
    *,
    user_agent: str | None = None,
    raise_for_status: bool | None = None,
    **options,  # any httpx2.AsyncClient option
)
```

The base class for an async client, with `async def` endpoints. It takes the same class arguments and arguments as [`ClientX`](#clientx), but it's an [`httpx2.AsyncClient`](https://pydantic.dev/docs/httpx2/api/#httpx2.AsyncClient): close it with `async with` or `await client.aclose()`, give it async transports, and make its event hooks `async` functions. See [Async clients](async.md).

## `Resource`

```py
class Users(Resource, prefix="/users", tags=["users"]):
    ...  # endpoints and plain methods
```

The base class for a group of endpoints, declared as on a client. Mount an instance as a class attribute of a client or another resource (`users = Users()`), and call its endpoints through the client (`api.users.retrieve(42)`).

| Class argument | Type | Default | Effect |
|---|---|---|---|
| `prefix` | `str` | the parent's, or `""` | Joined to the path of each endpoint in the class's body when the class is defined, with one slash between them. It doesn't depend on where the resource is mounted. |
| `tags` | `Sequence[str]` | none | Labels added to the parent's tags, which go before each endpoint's own. |

Endpoints on a resource can use the names a client reserves, such as `get`. See [Resources](resources.md).

## `AsyncResource`

```py
class Users(AsyncResource, prefix="/users", tags=["users"]):
    ...
```

The base class for a group of `async def` endpoints, with the same class arguments as [`Resource`](#resource). It mounts on an `AsyncClientX` or another `AsyncResource`.

## `method`

```py
from clientx import method

method.get(
    path: str = "",
    *,
    decoder: Callable[[Response], T] | None = None,
    stream: bool = False,
    deprecated: str | None = None,
    tags: list[str] | None = None,
    timeout: float | Timeout | None = ...,  # the client's
    raise_for_status: bool | None = None,  # the client's
)
```

The module of verb decorators: `get`, `post`, `put`, `patch`, `delete`, `head` and `options`, each sending its HTTP method, with the same arguments. Each decorates a `def` method of a `ClientX` or `Resource`, or an `async def` method of an `AsyncClientX` or `AsyncResource`, and turns it into an endpoint.

| Argument | Default | Effect |
|---|---|---|
| `path` | `""` | The path template, such as `"/users/{user_id}"`, relative to the base URL, after a resource's prefix. Each `{name}` is filled from the parameter with that name. |
| `decoder` | none | A function that turns the `httpx2.Response` into the endpoint's return value, in place of the decoding its annotation implies. A generator decoder streams. |
| `stream` | `False` | Return the open, unread response, for the caller to read and close. Only with `-> Response` and no `decoder`. |
| `deprecated` | none | The message of a `DeprecationWarning` that each call emits. |
| `tags` | none | Labels that group endpoints, each kept once. Nothing in ClientX uses them yet. |
| `timeout` | the client's | The request timeout, in seconds or as an `httpx2.Timeout`. `None` turns it off. |
| `raise_for_status` | the client's | Whether a 4xx or 5xx response raises `httpx2.HTTPStatusError`. |

The method's parameters build the request (see [Request helpers](#request-helpers)), and its return annotation decides what the endpoint returns: `-> None` nothing, `-> Response` the response, `-> str` or `-> bytes` the body, `-> Iterator[str]` or `-> Iterator[bytes]` the body streamed (`AsyncIterator` for `async def`), and any other type the JSON body, validated by Pydantic. See [Defining endpoints](endpoints.md) and [Responses](responses.md).

## Request helpers

```py
Url(**field_arguments)
Query(**field_arguments)
Header(**field_arguments)
Json(**field_arguments)
Body(**field_arguments)
Form(**field_arguments)
File(**field_arguments)
```

Each helper takes exactly the arguments of [`pydantic.Field`](https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.Field), and marks where a parameter's value goes. Put it in the parameter's outermost `Annotated`: `user_id: Annotated[int, Query(alias="userId")]`. ClientX reads `alias=`, the name the value is sent under. A default goes after `=`, not inside the helper. Every parameter needs a helper, except one named like a path placeholder, which fills it.

| Helper | Sends the value as | It takes |
|---|---|---|
| `Url()` | a path placeholder's value | a plain value |
| `Query()` | a query parameter | a plain value, a list of them, or a model, dataclass or mapping to spread |
| `Header()` | a header | a plain value, or a model, dataclass or mapping to spread |
| `Json()` | the JSON body, or one of its fields | anything Pydantic can serialize |
| `Body()` | the raw body | `str`, `bytes`, or a stream of `bytes` |
| `Form()` | a form field | a plain value, a list of them, or a model, dataclass or mapping to spread |
| `File()` | a file in a multipart form | `bytes`, a binary file, a `(filename, content[, content_type[, headers]])` tuple, or a list of them |

A plain value is a `str`, `int`, `float`, `bool`, `Enum`, `date`, `datetime`, `time`, `UUID`, `Decimal` or `bytes`, a `Literal` of those, or a `NewType` of one. See [Building requests](requests.md).

## `Send`

```py
Send(
    *,
    embed: bool | None = None,
    exclude_unset: bool | None = None,
    exclude_none: bool | None = None,
    exclude_defaults: bool | None = None,
    json_part: bool | None = None,
)
```

Options that change how a parameter is sent. Put it next to the helper, in the parameter's outermost `Annotated`: `ids: Annotated[list[str], Json(), Send(embed=True)]`. With several, the last one wins whole.

| Option | Effect |
|---|---|
| `embed` | Sends a lone JSON parameter under its name, as a field of a JSON object, instead of as the whole body. |
| `exclude_unset` | Leaves out the parameter when the caller doesn't pass it, and a model's fields that weren't set. |
| `exclude_none` | Leaves out a model's fields that are `None`. |
| `exclude_defaults` | Leaves out a model's fields that equal their defaults. |
| `json_part` | Sends a `Form()` parameter's value as a JSON part of a multipart form. |

Each option works with some helpers only, and one where it can't apply raises `DefinitionError` when the class is defined. See [Send](requests.md#send) for where each one works.

## Errors

| Error | Bases | Raised for |
|---|---|---|
| `ClientXError` | `Exception` | The base of the others, so `except ClientXError` catches any of them. |
| `DefinitionError` | `ClientXError`, `TypeError` | A client, resource or endpoint written in a way ClientX can't use. Almost always raised when the class is defined, so the mistake fails when its module is imported. |
| `ArgumentError` | `ClientXError`, `ValueError` | An argument value that can't be sent, raised before anything is sent. Its `parameter` attribute names the endpoint parameter. |
| `ToolError` | `ClientXError` | A tool call that failed, from [`clientx.tools`](#clientxtools). Its message is written for a model, and its `tool` attribute names the tool. |

```py
ArgumentError(message: str, *, parameter: str)
```

HTTP errors come from httpx2: `httpx2.HTTPStatusError` for a 4xx or 5xx response, and `httpx2.RequestError` for a failed request. See [Errors](errors.md).

## `clientx.tools`

```py
from clientx.tools import Tool, ToolError, list_tools

list_tools(client: ClientX | AsyncClientX) -> list[Tool]

tool.call(arguments: Mapping[str, Any] | None = None) -> Any  # on a ClientX
await tool.acall(arguments: Mapping[str, Any] | None = None) -> Any  # on an AsyncClientX
```

`list_tools` returns a `Tool` for each endpoint on the client and its mounted resources that a model can use: endpoints that stream, return the raw `Response`, or take an argument with no JSON form are left out. Nothing in it depends on an AI library.

| `Tool` attribute | Type | What it is |
|---|---|---|
| `name` | `str` | The attribute path from the client, joined with `_`: `users_create`. |
| `description` | `str` | The docstring up to its first section, or else the method and path. |
| `input_schema` | `dict` | The JSON Schema of the arguments, named as in the method, each described by its helper's `description=` or its docstring `Args:` entry. |
| `output_schema` | `dict` or `None` | The JSON Schema of the result, or `None` for `-> None`. |
| `read_only`, `destructive`, `idempotent` | `bool` | Hints from the HTTP method. |
| `is_async` | `bool` | Call it with `acall()` rather than `call()`. |

`call()` validates a model's arguments leniently, passes only those it gave, and returns JSON-ready data. A failed call raises `ToolError`, with a message for the model that never holds the host or query string, and the original error as its `__cause__`. See [AI tools](tools.md).

## From httpx2

| Name | Is | Used for |
|---|---|---|
| `Auth` | [`httpx2.Auth`](https://pydantic.dev/docs/httpx2/advanced/authentication/) | Writing an authentication scheme for a client's `auth=`. |
| `Request` | [`httpx2.Request`](https://pydantic.dev/docs/httpx2/api/#request) | The request a client sends, as event hooks and transports see it. |
| `Response` | [`httpx2.Response`](https://pydantic.dev/docs/httpx2/api/#response) | The `-> Response` annotation, decoders, and `stream=True`. |
| `Timeout` | [`httpx2.Timeout`](https://pydantic.dev/docs/httpx2/advanced/timeouts/) | A client's or an endpoint's `timeout=`. |

They're httpx2's own classes, re-exported so a client module doesn't need to import httpx2 for them: `clientx.Response` is `httpx2.Response`.

## `__version__`

```py
clientx.__version__  # "0.1.0"
```

The installed version of ClientX, as text, read from the package's metadata.
