# Grouping Endpoints with Resources

For larger APIs, group related endpoints into `Resource` classes, much like FastAPI's `APIRouter`. Mount an instance on your client, and its endpoints send through the client's connection and settings, so there's no second client to create or pass around. For `async def` endpoints, subclass `AsyncResource` and mount it on an `AsyncClientX` (see [Async clients](async.md)):

```python
from clientx import ClientX, Resource, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def retrieve(self, user_id: int) -> User: ...

    @method.post()
    def create(self, user: NewUser) -> User: ...


class ExampleAPI(ClientX):
    users = Users()


with ExampleAPI("https://api.example.com") as api:
    user = api.users.retrieve(42)  # GET /users/42
```

Type checkers see `api.users` as `Users`, and its endpoints keep their signatures.

## Prefixes

`prefix` is joined to the path of each endpoint in the class's body when the class is defined, with one slash between them, so `@method.post()` above is `POST /users`. It's absolute: a resource's paths don't depend on where it's mounted. Put a prefix shared by the whole API, such as `/v1`, in the client's base URL instead.

Placeholders in a prefix are filled from the endpoint's parameters like any other: with `prefix="/repos/{owner}/{repo}"`, each endpoint needs `owner` and `repo` parameters, or the class raises `DefinitionError` when it's defined.

### Subclassing a resource

A resource subclass inherits its parent's `prefix` unless it sets its own. Either way, the prefix applies only to the endpoints defined in the subclass's body: inherited endpoints keep the parent's paths.

With `class Admins(Users, prefix="/admins")`, a new endpoint `@method.get("/{admin_id}")` in `Admins` is `GET /admins/{admin_id}`, but the inherited `retrieve` is still `GET /users/{user_id}`.

## Tags

`tags=` labels a resource's endpoints, to group them:

```python
from clientx import Resource, method


class Users(Resource, prefix="/users", tags=["users"]):
    @method.get("/{user_id}", tags=["read"])
    def retrieve(self, user_id: int) -> None: ...


class Admins(Users, tags=["admin"]):
    @method.post("/{user_id}/promote", tags=["write"])
    def promote(self, user_id: int) -> None: ...
```

`retrieve` is tagged `["users", "read"]`: a resource's tags go before each endpoint's own, and each tag is kept once, in order. A subclass's tags are added to its parent's, so `promote` is tagged `["users", "admin", "write"]`, and a subclass without `tags` keeps its parent's. Like a prefix, tags are fixed when the class is defined, so they don't depend on where the resource is mounted.

ClientX keeps the tags on each endpoint for tooling, such as describing endpoints as AI tools ([#138](https://github.com/slatecipher/ClientX/issues/138)), but nothing in ClientX uses them yet.

## Mounting and nesting

Mount an instance (`users = Users()`), not the class: `users = Users` raises `DefinitionError` when the class is defined. Calling an endpoint on a resource that isn't mounted on a client, such as `Users().retrieve(42)`, raises `DefinitionError` too.

Mount resources on other resources to nest them, for example `api.repos.issues.retrieve(...)`. Each keeps its own prefix: prefixes don't add up through nesting.

A `Resource` mounts on a `ClientX` or another `Resource`, and an `AsyncResource` on an `AsyncClientX` or another `AsyncResource`. Mounting one on the other kind raises `DefinitionError` when the class is defined.

A resource doesn't refer to the client class, so resources can live in their own modules.

Names that a client reserves, such as `get` or `headers`, are free for endpoints on a resource (see [Endpoint names](endpoints.md#endpoint-names)).

## Plain methods

A client or resource can also have ordinary, undecorated methods. They aren't endpoints, but they can call endpoints through `self`. They're the place for logic around requests, such as following pages or normalizing an argument:

```python
import httpx2
from clientx import ClientX, Resource, method
from pydantic import BaseModel


class NamedLink(BaseModel):
    name: str
    url: str


class Page(BaseModel):
    count: int
    next: str | None
    results: list[NamedLink]


class Pokemon(BaseModel):
    id: int
    name: str


class PokemonResource(Resource, prefix="/pokemon"):
    @method.get()
    def page(self, limit: int = 20, offset: int = 0) -> Page:
        """List Pokémon, one page at a time."""
        ...

    @method.get("/{name}")
    def retrieve(self, name: str) -> Pokemon:
        """Fetch one Pokémon by its lowercase name."""
        ...

    def next_page(self, page: Page) -> Page | None:
        """Fetch the page after `page`, or return None after the last one."""
        if page.next is None:
            return None
        params = httpx2.URL(page.next).params
        return self.page(limit=int(params["limit"]), offset=int(params["offset"]))

    def find(self, name: str) -> Pokemon:
        """Fetch a Pokémon by name, whatever its case or surrounding spaces."""
        return self.retrieve(name.strip().lower())


class PokeAPI(ClientX):
    pokemon = PokemonResource()


with PokeAPI("https://pokeapi.co/api/v2") as api:
    first = api.pokemon.page()
    second = api.pokemon.next_page(first)
```

- `next_page` reads the next page's parameters from the `next` URL. The URL itself can't be passed back as a path value, because path values are percent-encoded.
- `find` lowercases the name before calling `retrieve`. Endpoint bodies never run, and ClientX sends values as they're given, so a plain method is where to change one.
