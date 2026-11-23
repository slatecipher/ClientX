# Defining Endpoints

An endpoint is a method whose signature describes one API call, in two halves:

- **The parameters build the request.** A parameter named like a `{placeholder}` in the path fills it, and the others become query parameters, headers, form fields, files or the body (see [Building requests](requests.md)).
- **The return annotation describes the response.** ClientX decodes the response into that type (see [Responses](responses.md)).

<!-- docs_src/endpoints/defining.py -->
```python
from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...


with UsersAPI("https://api.example.com") as api:
    user = api.get_user(42)  # GET /users/42, decoded into a User
```

`get_user(42)` sends `GET /users/42`, because `user_id` matches `{user_id}`, and returns the JSON response as a `User`. The two halves are independent: `User`'s fields come from the response, not from the arguments.

Import the decorators' module, `from clientx import method`, and decorate each endpoint with the verb it sends: `@method.get(...)`, `@method.post(...)`, `@method.put(...)`, `@method.patch(...)`, `@method.delete(...)`, `@method.head(...)` or `@method.options(...)`. They decorate `def` methods of a `ClientX` or a `Resource`, and `async def` methods of an `AsyncClientX` or an `AsyncResource` (see [Async clients](async.md)).

## Options

Each decorator takes the path, then these keyword options:

| Option | Default | Effect |
|---|---|---|
| `path` | `""` | The path template, relative to the client's base URL. A resource's prefix is joined onto it, so `@method.get()` on a resource with `prefix="/users"` is `GET /users`. On a client, `@method.get()` calls the base URL, which httpx2 always ends with `/`. See [Path parameters](requests.md#path-parameters). |
| `decoder` | none | A function that turns the `httpx2.Response` into the return value, instead of the decoding the return annotation implies. See [Your own decoder](responses.md#your-own-decoder). |
| `stream` | `False` | `True` returns the open, unread response: annotate the endpoint `-> Response`, with no `decoder`. See [The open response](responses.md#the-open-response). |
| `deprecated` | `None` | A message: each call emits a `DeprecationWarning` with it. See [Deprecating endpoints](#deprecating-endpoints). |
| `tags` | none | Labels that group endpoints, each kept once. A resource's tags go in front (see [Tags](resources.md#tags)). AI tools carry them, to choose which to register (see [Choosing tools](tools.md#choosing-tools)). |
| `tool_options` | none | Hints about what the endpoint does, for AI tools, such as `ToolOptions(read_only=True)` from `clientx.tools`. Each hint you set is used as it is, and each you leave out comes from the HTTP method, so without `tool_options` all three do. See [Where each hint comes from](tools.md#where-each-hint-comes-from). |
| `timeout` | the client's | Seconds, or an `httpx2.Timeout`, for this endpoint's requests. `None` turns the timeout off. |
| `raise_for_status` | the client's | Whether a 4xx or 5xx response raises `httpx2.HTTPStatusError`. Clients raise by default. See [Errors for 4xx and 5xx responses](responses.md#errors-for-4xx-and-5xx-responses). |

<!-- docs_src/endpoints/options.py -->
```python
from clientx import ClientX, Response, method


class FilesAPI(ClientX):
    @method.get("/files/{name}", timeout=60.0, raise_for_status=False)
    def download(self, name: str) -> Response:
        """Fetch a file. A 404 is returned as a response instead of raising."""
        ...
```

## The method

- **The body never runs.** Write `...`, after the docstring if there is one.
- **The first parameter receives the client or resource.** Name it `self`, as usual. It must be positional.
- **Every other parameter sends one value.** Positional-only and keyword-only parameters work as in any method, but `*args` and `**kwargs` can't be endpoint parameters: each value needs a parameter of its own, which decides where it goes in the request.
- **The return annotation is required.** It decides what the endpoint returns.
- **A docstring is optional, but worth writing.** It documents the endpoint in editors' hovers and `help()`, and for a model that calls it as a tool, where its `Args:` describe the arguments (see [Writing descriptions for a model](tools.md#writing-descriptions-for-a-model)).
- **Type checkers see the method's own signature**, so `api.get_user` takes `user_id: int` and returns a `User`. With `decoder=`, they also check that the decoder's declared return type matches the annotation, and the decoder validates the value itself, such as by building a model (see [Your own decoder](responses.md#your-own-decoder)).

A mistake in an endpoint, such as a missing return annotation or a placeholder that names no parameter, raises `DefinitionError` when the class is defined, so it fails when its module is imported, not on its first call (see [Errors](errors.md)).

## Empty method bodies and mypy

Pyright accepts a body of `...`, but not a body that's only a docstring: for an endpoint whose return type isn't `None`, it reports `Function with declared return type "User" must return value on all code paths`. Mypy reports `Missing return statement  [empty-body]` for every endpoint whose return type isn't `None`, even with `...`. Turn that one check off for your client modules, either at the top of the file:

```python no-check
# mypy: disable-error-code="empty-body"
```

or in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "myapp.clients"
disable_error_code = ["empty-body"]
```

Mypy still checks everything else in those modules, including the return types of calls to your endpoints.

## Deprecating endpoints

Give `deprecated=` the message to show:

<!-- docs_src/endpoints/deprecated.py -->
```python
from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/v1/users/{user_id}", deprecated="Use get_user() instead.")
    def get_user_v1(self, user_id: int) -> User: ...

    @method.get("/v2/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...
```

Each call to `get_user_v1` emits a `DeprecationWarning` with that message, pointing at the caller's line, before the request is sent. Python shows a `DeprecationWarning` only when it's triggered by code in `__main__`, or under a test runner such as pytest. To send warnings to your logs, call `logging.captureWarnings(True)`: they then appear on the `py.warnings` logger.

A deprecated endpoint is still an [AI tool](tools.md): its `Tool.deprecated` holds the message, and its description ends with it, so a model prefers the replacement.

## Endpoint names

A `ClientX` is an `httpx2.Client`, so an endpoint or mounted resource on a client can't use a name the client already has: every name of `httpx2.Client`, such as `get`, `post`, `send`, `headers` or `close`, as well as ClientX's own. Such a name raises `DefinitionError` when the class is defined, because overriding it would break the client. Put the endpoint on a [resource](resources.md) instead, where those names are free. An `AsyncClientX` reserves the names of `httpx2.AsyncClient` the same way.

An endpoint belongs to the class whose body it's in. It can have a second name there (`QueryDevices = query_devices`), which sends the same request. Putting it in another client's or resource's body raises `DefinitionError`, since that class's prefix would change its path too: declare it again there.

An endpoint's name hides any other meaning of that name for the rest of the class body:

- If you import the decorators themselves (`from clientx.method import get`), an endpoint named like one, such as `get`, replaces it, so a later `@get(...)` fails when the class is defined. Decorating with `@method.get(...)`, as these docs do, avoids that.
- If an endpoint is named `list` (or `dict`, `type`...), a later `list[Post]` in an annotation or a decorator argument fails when the class is defined: `TypeError: 'function' object is not subscriptable`. Pyright reports it too. Define that endpoint last in the class, or write `builtins.list[Post]` after it.

## Requests without an endpoint

A client is an `httpx2.Client`, so its own methods send a request with the client's base URL and settings, for a one-off call that doesn't need an endpoint:

<!-- docs_src/endpoints/one_off_request.py -->
```python
from clientx import ClientX


class ExampleAPI(ClientX): ...


with ExampleAPI("https://api.example.com") as api:
    response = api.get("/status")
    response.raise_for_status()
```

These are httpx2's methods, so they return the `httpx2.Response` as it is: nothing is decoded, and a 4xx or 5xx response doesn't raise until you call `raise_for_status()`. For a call you make more than once, declare an endpoint.
