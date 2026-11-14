# Grouping Endpoints with Resources

For larger APIs, group related endpoints into `Resource` classes, much like FastAPI's `APIRouter`. Mount an instance on your client, and its endpoints send through the client's connection and configuration, so there's no second client to create or pass around. For `async def` endpoints, subclass `AsyncResource` and mount it on an `AsyncClientX` (see [Async clients](async.md)):

```python
from clientx import ClientX, Resource, Response, method
from clientx.decoders import ModelDecoder
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users", tags=["users"]):
    @method.get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        ...

    @method.post()
    def create(self, json: dict[str, str]) -> Response:
        ...


class ExampleAPI(ClientX):
    users = Users()


api = ExampleAPI("https://api.example.com")
user = api.users.retrieve(42)  # GET /users/42
```

Type checkers see `api.users` as `Users`, and its endpoints keep their signatures.

## Prefixes and tags

`prefix` is joined to the path of each endpoint in the class when the class is defined, so tools and logs show full paths. It's absolute: a resource's paths don't depend on where it's mounted. Put a prefix shared by the whole API, such as `/v1`, in the client's base URL instead.

Placeholders in a prefix are filled from method arguments like any other: with `prefix="/repos/{owner}/{repo}"`, each endpoint needs `owner` and `repo` parameters.

`tags` are added before each endpoint's own tags.

### Subclassing a resource

A resource subclass inherits its parent's `prefix` and `tags` unless it sets its own. Either way, they apply only to the endpoints defined in the subclass's body: inherited endpoints keep the parent's paths and tags. A subclass's `tags` replace the parent's rather than adding to them.

With `class Admins(Users, prefix="/admins")`, a new endpoint `@method.get("/{admin_id}")` in `Admins` is `GET /admins/{admin_id}`, but the inherited `retrieve` is still `GET /users/{user_id}`.

## Mounting and nesting

Mount an instance (`users = Users()`), not the class. Calling an endpoint on a resource that isn't mounted on a client, such as `Users().retrieve(42)`, raises `UnboundResourceError`.

Mount resources on other resources to nest them, for example `api.repos.issues.retrieve(...)`. Each keeps its own prefix.

A resource doesn't refer to the client class, so resources can live in their own modules.

## Endpoint names

Names that `ClientX` itself uses, such as `close`, are free for endpoints on a resource.

An endpoint belongs to the class whose body it's in. It can have a second name there (`QueryDevices = query_devices`), which sends the same request and is listed once as an AI tool. Putting it in another resource's or client's body raises `TypeError` when that class is defined, since that resource's prefix would change its path too: declare it again there.

An endpoint's name hides any other meaning of that name for the rest of the class body:

- If you import the decorators themselves (`from clientx.method import get`), an endpoint named like one, such as `get`, replaces it, so a later `@get(...)` fails when the class is defined. Decorating with `@method.get(...)`, as these docs do, avoids that.
- If an endpoint is named `list` (or `dict`, `type`, ...), a later `list[Post]` in an annotation or a decorator argument fails when the class is defined: `TypeError: 'function' object is not subscriptable`. Pyright reports it too. Define that endpoint last in the class, or write `builtins.list[Post]` after it.

## Plain methods

A client or resource can also have ordinary, undecorated methods. They aren't endpoints, but they can call endpoints through `self`. They're the place for logic around requests, such as following pages or normalizing an argument:

```python
from typing import Annotated

import httpx2
from clientx import ClientX, Query, Resource, Response, method
from clientx.decoders import ModelDecoder
from pydantic import BaseModel


class NamedLink(BaseModel):
    name: str
    url: str


class Page(BaseModel):
    count: int
    next: str | None
    results: list[NamedLink]


class Pokemon(Resource, prefix="/pokemon"):
    @method.get(decoder=ModelDecoder(Page))
    def page(self, limit: Annotated[int, Query()] = 20, offset: Annotated[int, Query()] = 0) -> Page:
        """List Pokémon, one page at a time."""
        ...

    @method.get("/{name}")
    def retrieve(self, name: str) -> Response:
        """Fetch one Pokémon by its lowercase name."""
        ...

    def next_page(self, page: Page) -> Page | None:
        """Fetch the page after `page`, or return None after the last one."""
        if page.next is None:
            return None
        params = httpx2.URL(page.next).params
        return self.page(limit=int(params["limit"]), offset=int(params["offset"]))

    def find(self, name: str) -> Response:
        """Fetch a Pokémon by name, whatever its case or surrounding spaces."""
        return self.retrieve(name.strip().lower())


class PokeAPI(ClientX, base_url="https://pokeapi.co/api/v2"):
    pokemon = Pokemon()
```

- `next_page` reads the next page's parameters from the `next` URL. The URL itself can't be passed back as a path value, because path values are percent-encoded.
- `find` lowercases the name before calling `retrieve`. Endpoint bodies never run, and [argument validation](configuration.md#validating-arguments) never converts a value, so a plain method is where to change one.
