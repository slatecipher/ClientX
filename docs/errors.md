# Errors

ClientX raises two errors of its own, both derived from `ClientXError`, so `except ClientXError` catches either. Each also keeps a built-in base, so `except TypeError` and `except ValueError` keep working. Import them from `clientx`.

| Error | Base | Raised for |
|---|---|---|
| `DefinitionError` | `TypeError` | a client, resource or endpoint written in a way ClientX can't use |
| `ArgumentError` | `ValueError` | an argument value that can't be sent |

## `DefinitionError`

Almost every `DefinitionError` is raised when the class is defined, so a mistake fails when its module is imported, not on the first call. Its message names the class or endpoint, and the fix.

When an endpoint is decorated:

- It has no positional first parameter (usually `self`), or it has a `*args` or `**kwargs` parameter.
- It has no return annotation, or one ClientX can't decode: a type Pydantic can't validate, `Iterator` on an `async def` endpoint or `AsyncIterator` on a `def` one, or a stream of items other than `str` or `bytes` without a `decoder=`.
- It has `stream=True` without `-> Response`, or with a `decoder=`.
- Its `decoder=` can't work: the endpoint is annotated `-> None`, the decoder is `async def`, or it's a generator of the wrong kind, or on an endpoint that isn't annotated as a stream.

When the client or resource class is defined:

- The class subclasses both `ClientX` and `AsyncClientX`, or both `Resource` and `AsyncResource`.
- An endpoint is the wrong kind for its class: `async def` on a `ClientX` or `Resource`, or `def` on an `AsyncClientX` or `AsyncResource`.
- An endpoint or mounted resource has a name the client already uses (see [Endpoint names](endpoints.md#endpoint-names)), or the endpoint is already in another class's body.
- A resource is mounted on the other kind of client or resource, or on a class that isn't one.
- The path has a brace that isn't part of a placeholder, a placeholder other than `{name}` or `{name:path}`, or a placeholder, a resource prefix's included, that names no parameter. A placeholder's parameter isn't a plain value, or has a helper other than `Url()`, or a `Url()` parameter has no placeholder.
- A helper is nested inside a parameter's type, has a default inside it, or is on a model's field.
- A parameter's value can't go to its part, such as a list for a header, or a field of a spread model that isn't a plain value. The parameters make more than one kind of body, or more than one is marked `Body()`.

See [Building requests](requests.md) for the rules behind the last four.

At call time:

- An endpoint is called on a resource that isn't mounted on a client, or on an object that isn't a client or a resource.
- An endpoint is declared outside a client or resource class, so it has no request to build.

## `ArgumentError`

An `ArgumentError` is raised before the request is sent, when an argument's value can't be sent as it is. Its `parameter` attribute names the parameter. A path value raises it when it would call a different path: `None`, an empty value, or a `{name:path}` value with a leading, trailing or doubled slash (see [Path parameters](requests.md#path-parameters)).

```python
from clientx import ArgumentError, ClientX, method


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: str) -> None: ...


with UsersAPI("https://api.example.com") as api:
    try:
        api.get_user("")
    except ArgumentError as error:
        print(error.parameter)  # user_id: no request was sent
```

## Other errors

- Calling an endpoint with arguments that don't fit its signature raises `TypeError`, as for any method.
- A response body that doesn't match the return annotation raises `pydantic.ValidationError`, which is a `ValueError` (see [Typed results](responses.md#typed-results)). A decoder's own exceptions reach the caller unchanged.
- HTTP errors come from httpx2: `httpx2.HTTPStatusError` for a 4xx or 5xx response (see [Errors for 4xx and 5xx responses](responses.md#errors-for-4xx-and-5xx-responses)), and `httpx2.RequestError` for a failed request, such as a connection error or a timeout. Both are `httpx2.HTTPError`.

## Annotations

ClientX evaluates an endpoint's annotations when the method is decorated, so endpoints work in modules with `from __future__ import annotations`. Like Pydantic, it evaluates them against the module's globals: a type defined inside a function can't be named in a string annotation, and a type defined further down the module isn't defined yet, which raises `NameError`. Define the models an endpoint uses before its class.
