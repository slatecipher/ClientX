# Building Requests

Each parameter after `self` sends one value. Where it goes is decided once, when the class is defined, the way FastAPI decides where an incoming request's values come from, in reverse:

1. A parameter named like a `{placeholder}` in the path fills it.
2. A parameter with a helper, such as `Annotated[str, Header()]`, goes where the helper says.
3. Any other parameter goes to the JSON body if its type is a model, a mapping, a collection or a dataclass (or a union with one), and to the query string otherwise.

```python
from typing import Annotated

from clientx import ClientX, Header, Response, method
from pydantic import BaseModel


class NewPost(BaseModel):
    title: str
    body: str


class PostsAPI(ClientX):
    @method.get("/users/{user_id}/posts")
    def list_posts(self, user_id: int, page: int = 1, tag: str | None = None) -> Response: ...

    @method.post("/posts")
    def create_post(self, post: NewPost, request_id: Annotated[str, Header()]) -> Response: ...
```

- `list_posts(7, tag="news")` sends `GET /users/7/posts?page=1&tag=news`. `page`'s default is sent, and `tag` is left out when it's `None`.
- `create_post(NewPost(title="Hi", body="First post"), "r-1")` sends `POST /posts` with the JSON body `{"title":"Hi","body":"First post"}` and the header `request-id: r-1`.

A parameter's name has no meaning of its own: one named `json` or `headers` follows the same rules as any other.

## The helpers

| Helper | Sends the value as | It takes |
|---|---|---|
| `Url()` | a path placeholder's value | a plain value |
| `Query()` | a query parameter | a plain value or a list of them, or a model, dataclass or mapping to [spread](#spreading-a-model-dataclass-or-mapping) |
| `Header()` | a header | a plain value, or a model, dataclass or mapping to spread |
| `Json()` | the JSON body, or one of its fields | anything Pydantic can turn into JSON |
| `Body()` | the raw body | `str`, `bytes`, or an iterable of `bytes` |
| `Form()` | a form field | a plain value or a list of them, or a model, dataclass or mapping to spread |
| `File()` | a file in a multipart form | what httpx2's `files=` takes for one file: `bytes`, a file object, or a `(filename, content, content_type)` tuple |

A plain value is anything that isn't a model, a collection (a mapping, list, tuple, set...) or a dataclass: a `str`, `int`, `float`, `bool`, `Enum`, `datetime`, `UUID`, `Literal` and so on. `str` and `bytes` are plain.

The helpers are built on `pydantic.Field` and take its arguments. ClientX reads `alias=`, the name the value is sent under: `Annotated[int, Query(alias="userId")]`. A `description=` or a constraint such as `ge=1` documents the parameter, for example in a model's JSON Schema, but ClientX doesn't check arguments against them before sending.

A parameter's default goes after `=`, as for any parameter: `page: Annotated[int, Query()] = 1`. A default inside the helper, such as `Query(default=1)` or `Query(1)`, raises `DefinitionError`, since ClientX doesn't read it there.

## Path parameters

Each `{placeholder}` in the path, including one in a [resource's prefix](resources.md#prefixes), is filled from the parameter with the same name. A placeholder that names no parameter raises `DefinitionError`, and so does a placeholder's parameter that isn't a plain value or has a helper other than `Url()`. `Url()` is optional: it only marks the parameter, for example to describe it, and raises `DefinitionError` if the path has no placeholder for it.

A value becomes text, as a query value does (see [Query parameters and headers](#query-parameters-and-headers)), and is then percent-encoded, so a value such as `"a/b"` or `"../admin"` stays one path segment and can't add a query string. Don't encode values yourself: a `%` would be encoded again. For a value that spans segments, such as a file path, use `{name:path}`, which keeps the slashes and still encodes each segment:

```python
from clientx import ClientX, Response, method


class ReposAPI(ClientX):
    @method.get("/repos/{owner}/{repo}/contents/{file_path:path}")
    def get_file(self, owner: str, repo: str, file_path: str) -> Response: ...
```

`get_file("ada", "notes", "docs/intro.md")` sends `GET /repos/ada/notes/contents/docs/intro.md`.

`{{` and `}}` are literal braces. Any other brace, such as `{user-id}` or a converter other than `path` (`{user_id:int}`), raises `DefinitionError` when the class is defined.

A value that would call a different path raises `ArgumentError` before anything is sent: `None`, which would be sent as `null`; an empty value, since `/users/{user_id}` with `""` would call `/users/`; and in a `{name:path}` value, a leading, trailing or doubled slash. The error's `parameter` attribute names the parameter.

## Query parameters and headers

```python
from enum import Enum
from typing import Annotated

from clientx import ClientX, Header, Query, Response, method


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class ItemsAPI(ClientX):
    @method.get("/items")
    def list_items(
        self,
        item_type: Annotated[str, Query(alias="type")],
        sort: Sort = Sort.NEWEST,
        tags: Annotated[list[str] | None, Query()] = None,
        request_id: Annotated[str | None, Header()] = None,
    ) -> Response: ...
```

`list_items("book", Sort.OLDEST, tags=["new", "used"], request_id="r-1")` sends `GET /items?type=book&sort=oldest&tags=new&tags=used` with the header `request-id: r-1`.

- **Names.** A value is sent under its helper's `alias`, or else under the parameter's name. A header's name has its underscores turned into hyphens, so `request_id` is sent as `request-id`; an alias is used exactly as given.
- **Lists.** A list repeats the query parameter (`tags=new&tags=used`), and so does a list of form fields. A header takes a plain value only. A list without a helper goes to the JSON body, like any collection, so mark a query parameter that's a list with `Query()`.
- **Text.** An `Enum` is sent as its value, a `datetime` as ISO 8601 text, a `UUID` as its string, and a number or `bool` as JSON text (`2`, `1.5`, `true`). Anything else is sent as `str(value)`.
- **`None` and defaults.** A value of `None` is left out, so an optional parameter defaults to `None`. A default that isn't `None` is sent, like any other value.
- **The client's own.** Values set with the client's `params=` and `headers=` are sent too.

## Bodies

A request has one kind of body: JSON, raw content, or a form. Parameters that would make two kinds, such as a `Json()` and a `Form()` parameter, raise `DefinitionError` when the class is defined. Query parameters and headers go with any body.

### JSON

A parameter marked `Json()`, or a model, mapping, collection or dataclass without a helper, goes to the JSON body:

- **One parameter that isn't a plain value is the whole body.** A `post: NewPost` parameter sends the model's JSON, and a `items: list[Item]` parameter sends the list.
- **Otherwise, each JSON parameter is a field of a JSON object**, under its alias or name: `title: Annotated[str, Json()]` and `tags: list[str]` send `{"title": "Hello", "tags": ["a", "b"]}`.
- **Values are sent as Pydantic sends them in JSON mode.** A model uses its own serializers and is sent by alias, so `user_id: int = Field(alias="userId")` is sent as `"userId"`. Dates, UUIDs and enums become JSON values. A model's field that's `None` is sent as `null`.
- **`None` is left out.** A JSON field whose value is `None` isn't sent, and a body parameter that's `None` sends no body.

### Raw content

`Body()` sends a `str`, `bytes`, or an iterable of `bytes` as the body, as it is. An endpoint takes at most one `Body()` parameter. Set the content type with a header:

```python
from typing import Annotated

from clientx import Body, ClientX, Header, Response, method


class NotesAPI(ClientX):
    @method.put("/notes/{note_id}")
    def save(
        self,
        note_id: int,
        text: Annotated[str, Body()],
        content_type: Annotated[str, Header(alias="Content-Type")] = "text/markdown",
    ) -> Response: ...
```

### Forms and files

`Form()` parameters are sent as form fields, URL-encoded. With a `File()` parameter, they're sent together as a multipart form:

```python
from typing import Annotated

from clientx import ClientX, File, Form, Response, method


class ProfilesAPI(ClientX):
    @method.post("/profile/avatar")
    def upload_avatar(
        self,
        image: Annotated[tuple[str, bytes, str], File()],
        caption: Annotated[str, Form()] = "",
    ) -> Response: ...
```

`upload_avatar(("me.png", data, "image/png"))` sends a multipart form with the file `image` and the field `caption`.

## Spreading a model, dataclass or mapping

A model, dataclass or mapping marked `Query()`, `Header()` or `Form()` is spread into that part: each field is sent as a separate value, under its alias or name (with underscores turned into hyphens for a header), and each item of a mapping under its own key.

```python
from typing import Annotated

from clientx import ClientX, Query, Response, method
from pydantic import BaseModel


class Filters(BaseModel):
    state: str = "open"
    assignee: str | None = None
    labels: list[str] = []


class IssuesAPI(ClientX):
    @method.get("/issues")
    def search(self, filters: Annotated[Filters, Query()]) -> Response: ...
```

`search(Filters(labels=["bug", "ui"]))` sends `GET /issues?state=open&labels=bug&labels=ui`.

- Each field follows the part's rules, as a parameter would: it must be a plain value or, except in a header, a list of them. A field that doesn't fit raises `DefinitionError` when the class is defined. A field that's `None` is left out.
- A model's own serializers apply, and its fields are sent by alias.
- A helper on a model's field, such as `assignee: Annotated[str, Header()]`, raises `DefinitionError`: the parameter's helper decides where all of the model's fields go.

## Where a helper goes

Put the helper in the parameter's outermost `Annotated`, around the full type with `None` included: `Annotated[int | None, Query()]`. A helper nested inside another type, such as `Annotated[int, Query()] | None` or `list[Annotated[str, Query()]]`, raises `DefinitionError`. Use one helper per parameter; if there are several, the last one wins.

Pydantic's own metadata, such as `Field(ge=1)`, isn't a helper and can go anywhere in the type.

To reuse an annotation, name it with a `type` alias, plain or generic:

```python
from typing import Annotated

from clientx import ClientX, Header, Query, Response, method

type UserId = Annotated[int, Query(alias="userId")]
type HeaderValue[T] = Annotated[T, Header()]


class PostsAPI(ClientX):
    @method.get("/posts")
    def list_posts(self, user_id: UserId, trace_id: HeaderValue[str | None] = None) -> Response: ...
```

## In a FastAPI app

The helpers are named like FastAPI's, but they do the opposite job: FastAPI's read the incoming request, and ClientX's build the outgoing one. In a FastAPI app that calls other APIs, import one of them under another name (`from clientx import Query as ClientQuery`), or use the module (`import clientx`, then `clientx.Query()`).

## Not supported yet

- **Partial updates from a model.** A model is sent with all of its fields, including those that were never set, and a field that's `None` is sent as `null`. For a PATCH, send a mapping, or a model with only the fields to change.
- **An explicit `null`.** A parameter whose value is `None` is always left out.
- **Leaving out a default.** A parameter's default is always sent.

[#135](https://github.com/slatecipher/ClientX/issues/135) tracks these.
