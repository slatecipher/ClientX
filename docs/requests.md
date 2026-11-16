# Building Request Payloads

ClientX maps method arguments into request parts in this order:

1. Arguments named like a path placeholder, such as `{user_id}`, fill the path (see [Path parameters](#path-parameters)).
2. Each remaining argument goes to the first of these that matches:
   1. Its name is a request part: `json`, `params`, `data`, `files`, or `headers`. The name wins even over an annotation, so a parameter named `data` is always sent as form data.
   2. It's annotated with a request part: `Annotated[..., Query()]`, `Header()`, `Form()`, `Body()`, or `File()`.
   3. Its value is a Pydantic model, which is expanded field by field. A `RootModel` has no fields to expand, so its value is the whole JSON body.
3. Arguments for the same request part are merged (see [When parameters share a request part](#when-parameters-share-a-request-part)).

## Path parameters

Each path value is converted like a query value (an `Enum` becomes its value, a `datetime` ISO 8601) and percent-encoded, so a value such as `"a/b"` or `"../admin"` stays one path segment and can't add a query string.

For a value that spans segments, such as a file path, use `{file_path:path}`: slashes are kept, and each segment is still encoded. Any other converter raises `PathTemplateError` when the class is defined.

A value that would change which path is called raises `PathValueError` before anything is sent:

- `None`, which would be sent as `null`.
- An empty value: `/users/{user_id}` with `""` would call `/users/`.
- In a `{name:path}` value, a leading, trailing, or doubled slash.

## By parameter name

```python
from clientx import ClientX, Response, method


class SearchClient(ClientX):
    @method.get("/search")
    def search(self, params: dict[str, object], headers: dict[str, str]) -> Response: ...
```

## With `Query`, `Header`, `Form`, `Body`, and `File`

Annotate a parameter with the helper for the request part it goes to:

| Helper | Request part | Example |
|---|---|---|
| `Query(key=None)` | Query parameters (`params`) | `Annotated[int \| None, Query("userId")]` |
| `Header(key=None)` | Headers | `Annotated[str, Header("Authorization")]` |
| `Form(key=None)` | Form data (`data`) | `Annotated[str, Form()]` |
| `Body()` | The JSON body (`json`) | `Annotated[UserChanges, Body()]` |
| `File()` | Multipart files (`files`) | `Annotated[dict[str, bytes], File()]` |

Every helper also takes `description=`, which describes the parameter or model field in its JSON Schema: it appears in any schema Pydantic builds from the annotation, such as a model's `model_json_schema()`, and in the argument schemas of [AI tools](ai-tools.md). `PathParam(description=...)` does the same for a path parameter. A description never changes the request.

```python
from enum import Enum
from typing import Annotated

from clientx import Body, ClientX, Header, Query, Response, method


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class ItemsClient(ClientX):
    @method.get("/items")
    def list_items(
        self,
        item_type: Annotated[str, Query("type")],
        sort: Annotated[Sort, Query()] = Sort.NEWEST,
        page: Annotated[int | None, Query()] = None,
    ) -> Response: ...

    @method.post("/items")
    def create_item(
        self,
        token: Annotated[str, Header("Authorization")],
        payload: Annotated[dict[str, object], Body()],
    ) -> Response: ...
```

`list_items("book", Sort.OLDEST)` sends `GET /items?type=book&sort=oldest`. `page` is left out because it's `None`.

### Keys and values

`Query`, `Header`, and `Form` send name-value pairs:

- `key` is the name the value is sent under, and it can differ from the parameter name. Without `key`, a single value (a string, number, or list) is sent under the parameter name, and a list repeats it (`?tag=a&tag=b`).
- `Header()` uses hyphens instead of underscores in the parameter name, so `request_id` is sent as `request-id`. A `key` is used exactly as given.
- A mapping, such as `dict[str, str]`, or a Pydantic model is merged into the part instead.
- Values are converted the way model fields are (see `DumpConfig` below): an `Enum` member becomes its `.value`, a `datetime` an ISO 8601 string, and a `UUID` a string. Numbers and booleans in headers are sent as text (`2`, `true`).
- A value of `None` is left out, so an optional parameter can default to `None`. To send an empty value, pass `""`.

`Body()` and `File()` take no key: they send the value as the JSON body or as the `files` mapping. Every helper takes `dump_config=` for Pydantic models (see [`DumpConfig`](#serialization-control-with-dumpconfig)).

### Reusing annotations

To reuse an annotation, name it with a `type` alias, plain or generic: `type UserId = Annotated[int | None, Query("userId")]`, or `type QueryParam[T] = Annotated[T, Query()]` used as `QueryParam[str]`.

### One helper, outermost

A helper applies to the whole parameter or field, so use one helper, in the outermost `Annotated`, around the full type with `None` included: `Annotated[int | None, Query()]`, or `QueryParam[int | None]` with an alias.

A helper nested inside another type, such as `Annotated[int, Query()] | None` or `list[Annotated[str, Query()]]`, and a second helper on the same parameter raise `MisplacedHelperError`: for a parameter when the class is defined, for a model field when the model is sent. If the request part depends on the value's type (a `str` header or a `dict` body, say), write separate endpoints.

Only ClientX's helpers must be outermost. Pydantic metadata, such as `Field` constraints, can go anywhere in the type, so each member of a union can have its own. For example, a path parameter that takes an ID or a login:

```python
from typing import Annotated

from clientx import ClientX, PathParam, Response, method
from pydantic import Field


class UsersClient(ClientX):
    @method.get("/users/{id_or_login}")
    def retrieve(
        self,
        id_or_login: Annotated[
            Annotated[int, Field(ge=1)] | Annotated[str, Field(pattern=r"^[a-z0-9-]+$")],
            PathParam(description="The user's numeric ID, or their lowercase login"),
        ],
    ) -> Response:
        """Fetch one user by ID or login."""
        ...
```

With `validate_arguments=True`, `retrieve(0)` and `retrieve("Ada!")` raise `ArgumentValidationError` before anything is sent, and the parameter's tool schema has both constraints (`anyOf` with `minimum` and `pattern`).

### In a FastAPI app

The helpers are named like FastAPI's, but they do the opposite job: FastAPI's read the incoming request, and ClientX's build the outgoing one. In a FastAPI app that calls other APIs, import one of them under another name (`from clientx import Query as ClientQuery`), or use the module (`import clientx`, then `clientx.Query("userId")`).

## By Pydantic model

```python
from typing import Annotated

from clientx import ClientX, Header, Query, Response, method
from pydantic import BaseModel


class CreateUserPayload(BaseModel):
    api_key: Annotated[str, Header("X-Api-Key")]
    notify: Annotated[bool, Query()] = False
    name: str
    email: str


class UsersClient(ClientX):
    @method.post("/users")
    def create_user(self, payload: CreateUserPayload) -> Response: ...
```

`create_user(CreateUserPayload(api_key="k-1", name="Ada", email="ada@example.com"))` sends `POST /users?notify=false` with an `X-Api-Key` header and the JSON body `{"name": "Ada", "email": "ada@example.com"}`.

A model passed without a helper is expanded field by field. A field annotated with `Query`, `Header`, or `Form` follows the same rules as a parameter: a single value is sent under its `key`, or under its alias or field name, and a mapping is merged into the part. Fields annotated with `Body` or `File` are merged into that part, so their value must be a mapping or a model: any other value, `None` included, raises `UnconsumableArgumentError` when the model is sent. Unannotated fields go to the JSON body.

## `None` values

`None` values are never sent as query parameters, headers, or form fields, whether they come from a single value, a mapping, or a model field. A JSON body keeps them as `null`. To leave them out of a JSON body too, use [`DumpConfig(exclude_none=True)`](#serialization-control-with-dumpconfig).

## When parameters share a request part

Arguments for the same request part are merged in parameter order, and later ones win: dicts are merged key by key, so a later `Header("X-Request-Id")` parameter overrides that key in an earlier `headers` dict, and any other value replaces the part. There's no warning, so put the parameter that should win last.

## Serialization control with `DumpConfig`

ClientX dumps models with `mode="json"` and `by_alias=True`. Dates, UUIDs, and decimals become JSON values, and each field is sent under its alias, which is usually the API's own name for it (`user_id: int = Field(alias="userId")`, or `alias_generator=to_camel` for a whole model).

`DumpConfig` takes these options of Pydantic's `model_dump`, and each one overrides ClientX's default:

| Option | Effect |
|---|---|
| `exclude_unset=True` | Send only the fields that were set. This is the usual choice for a PATCH. |
| `exclude_none=True` | Leave out `None` fields. Query parameters, headers, and form data always leave them out. |
| `exclude_defaults=True` | Leave out fields that still have their default value. |
| `include=...` / `exclude=...` | Send only the given fields, or leave them out, such as `exclude={"internal_note"}`. |
| `by_alias=False` | Send field names instead of aliases. |
| `mode="python"` | Keep Python objects such as `datetime`. httpx2 must be able to send them. |
| `context`, `round_trip`, `serialize_as_any`, `exclude_computed_fields`, `warnings` | Passed to `model_dump` as given. |

```python
from typing import Annotated

from clientx import Body, ClientX, DumpConfig, Response, method
from pydantic import BaseModel


class UserChanges(BaseModel):
    name: str | None = None
    title: str | None = None


class UsersClient(ClientX):
    @method.patch("/users/{user_id}")
    def update_user(
        self,
        user_id: str,
        changes: Annotated[UserChanges, Body(dump_config=DumpConfig(exclude_unset=True))],
    ) -> Response: ...
```

`update_user("42", UserChanges(title=None))` sends the JSON body `{"title": null}`, which clears the title and leaves the name alone.

### Lists and dicts of models

The JSON body is dumped the same way when it's a list or dict that holds models, such as a `json: list[User]` parameter for a bulk create, or `Annotated[list[User], Body()]`. A `DumpConfig` given to `Body()` applies to each model in it, except `include` and `exclude`: Pydantic applies those to the list or dict itself, so to leave a field out of every item, use `exclude={"__all__": {"internal_note"}}` (see Pydantic's [advanced include and exclude](https://docs.pydantic.dev/latest/concepts/serialization/#advanced-include-and-exclude)).
