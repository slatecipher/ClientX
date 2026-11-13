# Defining Endpoints

An endpoint is a method whose signature describes one API call, in two halves:

- **The parameters build the request.** A parameter named like a `{placeholder}` in the path fills it. The others become query parameters, headers, form fields, files, or the body (see [Building requests](requests.md)).
- **The return type describes the response.** The decorator's `decoder` turns the response into a value of that type.

```python
@method.get("/users/{user_id}", decoder=ModelDecoder(User))
def retrieve(self, user_id: int) -> User: ...
```

`retrieve(42)` sends `GET /users/42`, because `user_id` matches `{user_id}`, and returns the JSON response as a `User`. The two halves are independent: `User`'s fields come from the API's response, not from the arguments.

Import the decorators' module, `from clientx import method`, and decorate each endpoint with `@method.get(...)`, `@method.post(...)`, and so on. They decorate `def` methods of a `ClientX` or `Resource`, and `async def` methods of an `AsyncClientX` or `AsyncResource` (see [Async clients](async.md)). The decorators are:

- `get`
- `post`
- `put`
- `patch`
- `delete`
- `head`
- `options`

Each decorator accepts:

- `path` (optional; defaults to `""`, the base URL, or on a resource the prefix itself: `@method.get()` in a resource with `prefix="/users"` is `GET /users`)
- `decoder` (required when return type is not `Response` or `None`)
- `deprecated` (optional callable, including `DeprecatedMessage`)
- `tags` (optional list of labels; `list_tools()` can filter by them)
- `timeout` (optional per-endpoint `httpx2.Timeout` or seconds)
- `raise_for_status` (optional `True` or `False`; overrides the client's setting, see [Raising errors for 4xx and 5xx responses](configuration.md#raising-errors-for-4xx-and-5xx-responses))
- `validate_arguments` (optional `True` or `False`; overrides the client's setting, see [Validating arguments](configuration.md#validating-arguments))

```python
from clientx import ClientX, Response, method


class ItemsClient(ClientX):
    @method.post("/items")
    def create_item(self, json: dict[str, object]) -> Response:
        ...
```

There's no method for sending a raw request through a client: to call a URL the client has no method for, add an endpoint for it.

## Empty method bodies and mypy

Endpoint bodies never run, so `...` is all they need, after the docstring if there is one. Pyright accepts `...`, but not a body that's only a docstring: for an endpoint whose return type isn't `None`, it reports `Function with declared return type "User" must return value on all code paths`. Mypy reports `Missing return statement  [empty-body]` for every endpoint whose return type isn't `None`, even with `...`. Turn that one check off for your client modules, either at the top of the file:

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

## Deprecating Endpoints

Use `DeprecatedMessage` for warning-based deprecation:

```python
from clientx import ClientX, DeprecatedMessage, Response, method


class LegacyClient(ClientX):
    @method.get(
        "/v1/legacy",
        deprecated=DeprecatedMessage("Deprecated: use /v2/new-endpoint instead."),
    )
    def legacy(self) -> Response:
        ...
```

You can also pass any callable as `deprecated`, and it will run on endpoint invocation.
