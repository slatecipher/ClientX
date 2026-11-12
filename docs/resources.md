# Grouping Endpoints with Resources

For larger APIs, group related endpoints into `Resource` classes, much like FastAPI's `APIRouter`. Mount an instance on your client, and its endpoints send through the client's connection and configuration, so there's no second client to create or pass around:

```python
from clientx import ClientX, Resource, Response
from clientx.decoders import ModelDecoder
from clientx.methods import get, post
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users", tags=["users"]):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        ...

    @post()
    def create(self, json: dict[str, str]) -> Response:
        ...


class ExampleAPI(ClientX):
    users = Users()


api = ExampleAPI("https://api.example.com")
user = api.users.retrieve(42)  # GET /users/42
```

Type checkers see `api.users` as `Users`, and its endpoints keep their signatures.

- `prefix` is joined to the path of each endpoint in the class when the class is defined, so tools and logs show full paths. It's absolute: a resource's paths don't depend on where it's mounted. Put a prefix shared by the whole API, such as `/v1`, in the client's base URL instead.
- Placeholders in a prefix are filled from method arguments like any other: with `prefix="/repos/{owner}/{repo}"`, each endpoint needs `owner` and `repo` parameters.
- `tags` are added before each endpoint's own tags.
- Mount resources on other resources to nest them, for example `api.repos.issues.retrieve(...)`. Each keeps its own prefix.
- A resource doesn't refer to the client class, so resources can live in their own modules.
- Names that `ClientX` itself uses, such as `close`, are free for endpoints on a resource.
- A subclass keeps its parent's prefix and tags unless it sets its own.
- An endpoint's name hides any other meaning of that name for the rest of the class body:
  - If an endpoint is named like a decorator, such as `get`, later decorators refer to that method instead. Import the module (`from clientx import methods`) and write `@methods.get(...)`.
  - If an endpoint is named `list` (or `dict`, `type`, ...), a later `list[Post]` in an annotation or a decorator argument fails when the class is defined: `TypeError: 'function' object is not subscriptable`. Pyright reports it too. Define that endpoint last in the class, or write `builtins.list[Post]` after it.
- Mount an instance (`users = Users()`), not the class. Calling an endpoint on a resource that isn't mounted on a client, such as `Users().retrieve(42)`, raises `UnboundResourceError`.

## Plain methods

A client or resource can also have ordinary, undecorated methods. They aren't endpoints, so they aren't tools either, and they can call endpoints through `self`. They're the place for logic around requests, such as following pages or normalizing an argument:

```python
from typing import Annotated

import httpx2
from clientx import ClientX, Query, Resource, Response
from clientx.decoders import ModelDecoder
from clientx.methods import get
from pydantic import BaseModel


class NamedLink(BaseModel):
    name: str
    url: str


class Page(BaseModel):
    count: int
    next: str | None
    results: list[NamedLink]


class Pokemon(Resource, prefix="/pokemon"):
    @get(decoder=ModelDecoder(Page))
    def page(self, limit: Annotated[int, Query()] = 20, offset: Annotated[int, Query()] = 0) -> Page:
        """List Pokémon, one page at a time."""
        ...

    @get("/{name}")
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
