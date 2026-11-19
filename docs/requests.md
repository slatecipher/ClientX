# Building Requests

Each parameter after `self` sends one value. Where it goes is decided once, when the class is defined, and never guessed:

1. A parameter named like a `{placeholder}` in the path fills it.
2. Every other parameter has a helper, such as `Annotated[int, Query()]`, and goes where the helper says. A parameter without one raises `DefinitionError`, and the message suggests the helper it most likely needs.

```python
from typing import Annotated

from clientx import ClientX, Header, Json, Query, Response, method
from pydantic import BaseModel


class NewPost(BaseModel):
    title: str
    body: str


class PostsAPI(ClientX):
    @method.get("/users/{user_id}/posts")
    def list_posts(
        self,
        user_id: int,
        page: Annotated[int, Query()] = 1,
        tag: Annotated[str | None, Query()] = None,
    ) -> Response: ...

    @method.post("/posts")
    def create_post(
        self,
        post: Annotated[NewPost, Json()],
        request_id: Annotated[str, Header()],
    ) -> Response: ...
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
| `Body()` | the raw body | `str`, `bytes`, or a stream of `bytes`: an iterable on a sync client, an async iterable on an async one |
| `Form()` | a form field | a plain value or a list of them, or a model, dataclass or mapping to spread |
| `File()` | a file in a multipart form | `bytes`, a binary file, or a `(filename, content[, content_type[, headers]])` tuple, or a list of them; not `str` |

A plain value is a `str`, `int`, `float`, `bool`, `Enum`, `date`, `datetime`, `time`, `UUID`, `Decimal` or `bytes`, a `Literal` of those, or a `NewType` of one: each has one text form. Any other type, such as a class of your own, raises `DefinitionError` when the class is defined; annotate the parameter as `str` and convert the value at the call. `Any`, or no annotation, is the escape hatch: its value is sent by the same rules, and as `str(value)` if it's none of those types.

The helpers are built on `pydantic.Field` and take its arguments. ClientX reads `alias=`, the name the value is sent under: `Annotated[int, Query(alias="userId")]`. A `description=` or a constraint such as `ge=1` documents the parameter, for example in a model's JSON Schema, but ClientX doesn't check arguments against them before sending.

A parameter's default goes after `=`, as for any parameter: `page: Annotated[int, Query()] = 1`. A default inside the helper, such as `Query(default=1)` or `Query(1)`, raises `DefinitionError`, since ClientX doesn't read it there.

## Path parameters

Each `{placeholder}` in the path, including one in a [resource's prefix](resources.md#prefixes), is filled from the parameter with the same name. A placeholder that names no parameter raises `DefinitionError`, and so does a placeholder's parameter that isn't a plain value, can be `None` (`str | None`), or has a helper other than `Url()`. `Url()` is optional: it only marks the parameter, for example to describe it, and raises `DefinitionError` if the path has no placeholder for it.

A value becomes text, as a query value does (see [Query parameters and headers](#query-parameters-and-headers)), and is then percent-encoded, so a value such as `"a/b"` or `"../admin"` stays one path segment and can't add a query string. Don't encode values yourself: a `%` would be encoded again. For a value that spans segments, such as a file path, use `{name:path}`, which keeps the slashes and still encodes each segment:

```python
from clientx import ClientX, Response, method


class ReposAPI(ClientX):
    @method.get("/repos/{owner}/{repo}/contents/{file_path:path}")
    def get_file(self, owner: str, repo: str, file_path: str) -> Response: ...
```

`get_file("ada", "notes", "docs/intro.md")` sends `GET /repos/ada/notes/contents/docs/intro.md`.

There are no literal braces: a brace that isn't part of a placeholder, `{{` and `}}` included, raises `DefinitionError` when the class is defined, and so does a placeholder such as `{user-id}` or one with a converter other than `path` (`{user_id:int}`).

A value that would call a different path raises `ArgumentError` before anything is sent: `None`, which would be sent as `null` (it can only come through `Any`); an empty value, since `/users/{user_id}` with `""` would call `/users/`; and in a `{name:path}` value, a leading, trailing or doubled slash. The error's `parameter` attribute names the parameter.

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
        sort: Annotated[Sort, Query()] = Sort.NEWEST,
        tags: Annotated[list[str] | None, Query()] = None,
        request_id: Annotated[str | None, Header()] = None,
    ) -> Response: ...
```

`list_items("book", Sort.OLDEST, tags=["new", "used"], request_id="r-1")` sends `GET /items?type=book&sort=oldest&tags=new&tags=used` with the header `request-id: r-1`.

- **Names.** A value is sent under its helper's `alias`, or else under the parameter's name. A header's name has its underscores turned into hyphens, so `request_id` is sent as `request-id`; an alias is used exactly as given.
- **Lists.** A list repeats the query parameter (`tags=new&tags=used`), and so does a list of form fields. A tuple or set does too, but a set's order can change from run to run, and the URL with it: use a list for a fixed order. A header takes a plain value only, so join several yourself (`", ".join(tags)`), as you would for another list style, such as `tags=new,used`.
- **Text.** An `Enum` is sent as its value, a `datetime` as ISO 8601 text, a `UUID` as its string, and a number or `bool` as JSON text (`2`, `1.5`, `true`). A value of any other type can only come through `Any`, and is sent as `str(value)`.
- **`None` and defaults.** A value of `None` is left out, and so is an empty list and a `None` in one, so an optional parameter defaults to `None`. A default that isn't `None` is sent, like any other value.
- **One key, one value.** Two values sent under one key, such as two parameters with the same alias, or a parameter and a field of a spread model, raise `DefinitionError` when the class is defined, since one would be lost. Header names are compared ignoring case. A spread mapping's keys are known only at the call, so avoiding a clash with them is up to you.
- **The client's own.** Values set with the client's `params=` and `headers=` are sent too.

## Bodies

A request has one kind of body: JSON, raw content, or a form. Parameters that would make two kinds, such as a `Json()` and a `Form()` parameter, raise `DefinitionError` when the class is defined. Query parameters and headers go with any body.

### JSON

A parameter marked `Json()` goes to the JSON body:

- **One parameter that isn't a plain value is the whole body.** A `post: Annotated[NewPost, Json()]` parameter sends the model's JSON, and an `items: Annotated[list[Item], Json()]` parameter sends the list. To send it under its name instead, add [`Send(embed=True)`](#send): `ids: Annotated[list[str], Json(), Send(embed=True)]` sends `{"ids": [...]}`. Adding a second `Json()` parameter moves the first under its name, as in FastAPI, so `Send(embed=True)` also keeps the body's shape fixed if you might add one later.
- **Otherwise, each JSON parameter is a field of a JSON object**, under its alias or name: `title: Annotated[str, Json()]` and `tags: Annotated[list[str], Json()]` send `{"title": "Hello", "tags": ["a", "b"]}`.
- **Values are sent as Pydantic sends them in JSON mode.** A model uses its own serializers and is sent by alias, so `user_id: int = Field(alias="userId")` is sent as `"userId"`. Dates, UUIDs and enums become JSON values. A model's field that's `None` is sent as `null`, unless [`Send`](#send) says otherwise. A value Pydantic can't serialize raises `ArgumentError` before anything is sent.
- **`None`.** A JSON field that isn't passed is left out, and one passed explicitly as `None` is sent as `null`, as a PATCH that clears a field needs: `update(nickname=None)` sends `{"nickname": null}`. A body parameter that's `None` sends no body.

### Raw content

`Body()` sends a `str`, `bytes`, or a stream of `bytes` as the body, as it is: an iterable of `bytes` on a sync client, and an async iterable on an async one. Anything else, or a stream of the other kind, raises `DefinitionError` when the class is defined. An endpoint takes at most one `Body()` parameter. Set the content type with a header:

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

A file is `bytes`, a binary file (`open(path, "rb")`, `io.BytesIO`, `IO[bytes]`), or a `(filename, content[, content_type[, headers]])` tuple, where `headers` is a mapping of the file part's own headers. A list of files sends each under the same field. A `str` isn't a file: httpx2 would send the text itself as the file's content, so open the file yourself, or pass text as `bytes`. Any other type raises `DefinitionError` when the class is defined.

Without a file, the form is sent URL-encoded, so with an optional `File()` parameter the encoding depends on whether a file is passed.

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
- Every other field is sent, defaults included. To send only the fields that were set, or those that differ from their defaults, add [`Send(exclude_unset=True)` or `Send(exclude_defaults=True)`](#send).
- A model's own serializers apply, and its fields are sent by alias.
- A helper on a model's field, such as `assignee: Annotated[str, Header()]`, raises `DefinitionError`: the parameter's helper decides where all of the model's fields go.

## Send

The helper says where a parameter goes; `Send` says how it's sent there. Put it in the parameter's outermost `Annotated`, next to the helper. Its options:

| Option | Effect |
|---|---|
| `embed=True` | Sends a lone JSON parameter under its alias or name, as a field of a JSON object, instead of as the whole body. FastAPI's `Body(embed=True)` does the same for the request it receives. `Json()` only. |
| `exclude_unset=True` | Leaves out a model's fields that weren't set when it was made, so the server's defaults apply: a PATCH with only the fields to change. `Json()`, and a model spread into `Query()`, `Header()` or `Form()`. |
| `exclude_none=True` | Leaves out the fields of a model or Pydantic dataclass that are `None`, instead of sending `null`. `Json()` only: the other parts leave out `None` already. On a JSON field, a `None` passed explicitly is then left out too. |
| `exclude_defaults=True` | Leaves out the fields of a model or Pydantic dataclass that equal their defaults. `Json()`, and a spread model. |

Many APIs take a body such as `{"ids": [...]}`. Without `embed`, a lone `ids: Annotated[list[str], Json()]` would be the whole body, `[...]`:

```python
from typing import Annotated

from clientx import ClientX, Json, Query, Response, Send, method


class HostsAPI(ClientX):
    @method.post("/devices/actions")
    def contain(
        self,
        action_name: Annotated[str, Query()],
        ids: Annotated[list[str], Json(), Send(embed=True)],
    ) -> Response: ...
```

`contain("contain", ["host-1", "host-2"])` sends `POST /devices/actions?action_name=contain` with the JSON body `{"ids":["host-1","host-2"]}`.

To send it under another name, give it an alias with its helper: `ids: Annotated[list[str], Json(alias="deviceIds"), Send(embed=True)]` sends `{"deviceIds": [...]}`. ClientX reads the name only from its own helpers, so a plain `pydantic.Field(alias=...)` doesn't change it.

`exclude_unset`, `exclude_none` and `exclude_defaults` are Pydantic's dump options. They apply to a model anywhere in the value, such as each item of a `list[User]`. Each must fit the type, or it raises `DefinitionError`, since Pydantic would ignore it silently: `exclude_unset` needs a Pydantic model, the only kind that records which fields were set, and the other two a model or a Pydantic dataclass (`pydantic.dataclasses.dataclass`), not a standard library one.

With several `Send` in one `Annotated`, such as one from a `type` alias and one on the parameter, the last one wins whole, as the last helper does.

`Send` where it can't apply raises `DefinitionError` when the class is defined: an option on a part that doesn't take it (set to `False` too), such as `embed` outside `Json()`; any `Send` on a path parameter; a dump option on a type it can't affect; or a `Send` nested inside the parameter's type or on a model's field.

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

- **Leaving out a parameter's default.** A parameter's default is always sent. `Send(exclude_defaults=True)` applies to a model's fields, not to the parameter itself.
