# AI Tools

A ClientX client already describes each of its endpoints: its name, its docstring, and the types of its arguments and result. `clientx.tools` turns that into tools a model can call. `list_tools(client)` returns one `Tool` per endpoint, and `tool.call(arguments)` calls it with the arguments the model chose, through the client, with its base URL, auth and settings:

<!-- docs_src/tools/list_tools.py -->
```python
from typing import Annotated

from clientx import ClientX, Json, Query, Resource, method
from clientx.tools import ToolError, list_tools
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get()
    def search(self, name: Annotated[str | None, Query(description="Only users with this name.")] = None) -> list[User]:
        """List users."""
        ...

    @method.post()
    def create(self, user: Annotated[NewUser, Json()]) -> User:
        """Create a user.

        Args:
            user: The user to create. Its name must be unique.
        """
        ...


class ExampleAPI(ClientX, base_url="https://api.example.com"):
    users = Users()


api = ExampleAPI()
tools = {tool.name: tool for tool in list_tools(api)}  # users_search, users_create
create = tools["users_create"]
print(create.description)  # Create a user.
print(create.input_schema)  # {"properties": {"user": {"description": "The user to create. ...", ...}}, ...}

try:
    user = create.call({"user": {"name": "Ada"}})  # {"id": 1, "name": "Ada"}
except ToolError as error:
    print(error)  # users_create: the API answered 409 Conflict to POST /users: {"detail":"name taken"}
```

`clientx.tools` doesn't depend on any AI library. Register the tools with the framework your model runs in, such as an MCP server: each tool has what a framework asks for (see [Using a framework](#using-a-framework)).

## Which endpoints become tools

Every endpoint on the client, and on the resources mounted on it, is a tool, except one that's private or that a model can't use well. `list_tools` leaves these out:

| The endpoint | Why it's left out | To make it a tool |
|---|---|---|
| Streams: `-> Iterator[...]`, `-> AsyncIterator[...]` or `stream=True` | A stream can be endless, and wouldn't fit in a model's context. | Add an endpoint that returns the data whole, or a page of it. |
| Returns the raw `Response` | A response object isn't data a model can read. | Annotate what the API returns, such as a model or `dict[str, Any]`. |
| Returns `bytes`, such as a file download | A model can't read binary data, and it often isn't text, so it wouldn't become JSON. | Annotate text as `str`. Keep a file download for your code. |
| Takes an argument with no JSON form, such as a binary file (`BinaryIO`) | A model sends its arguments as JSON. | Keep it for your code: a model can't send a file. |
| Has a private name, which starts with `_`, such as `_delete`, or is on a resource mounted under one | It's private in Python, so it's private from a model too: a method of yours can check something before calling it, and a model can't go around the check (see [Guarding an endpoint](#guarding-an-endpoint)). | Name it without the leading `_`. |

An endpoint's second name in its class is the same endpoint, so it's listed once. A second name that isn't private is listed even when the first one is.

A method of your own becomes a tool too with `@tool`: see [Tools that aren't endpoints](#tools-that-arent-endpoints).

## What a tool has

| Attribute | What it is |
|---|---|
| `name` | The endpoint's attribute path from the client, joined with `_`: `api.users.create` is `users_create`. |
| `description` | The endpoint's docstring, up to its first section, such as `Args:`. Without a docstring, the method and path: `GET /users/{user_id}`. |
| `input_schema` | The JSON Schema of the arguments: an object with one property per parameter, named as in the method. |
| `output_schema` | The JSON Schema of the result, from the return annotation, or `None` for `-> None`. |
| `read_only`, `destructive`, `idempotent` | Hints about what it does: it changes nothing; it can delete or overwrite what's there; calling it again has no further effect. Each is set on its own: an endpoint's comes from its `tool_options=`, or else its HTTP method, and a tool method's from `@tool`, or else it's `False`. See [Hints](#hints). |
| `tags` | The endpoint's tags, its resource's first (see [Tags](resources.md#tags)), to choose which tools to register by. |
| `deprecated` | The endpoint's `deprecated=` message, or `None`. A deprecated endpoint is still a tool, and its description starts with `Deprecated:` and the message, so a model, or a client that shows only the first line, sees the replacement. |
| `is_async` | The endpoint is `async def`, so the tool is called with `await tool.acall(arguments)` instead of `call()`. |

## Descriptions

A model chooses a tool and fills in its arguments from what the tool says, so the descriptions matter:

- **The tool's description** is the endpoint's docstring, up to its first section. Put what the endpoint does, and when to use it, in the summary and the paragraphs after it. A [deprecated](endpoints.md#deprecating-endpoints) endpoint's description starts with `Deprecated:` and its message, such as `Deprecated: Use get_user() instead.`, then a blank line and the docstring.
- **An argument's description** is its helper's `description=`, such as `Query(description="...")`, or else its entry in the docstring's `Args:` section. A [Google-style](../CONTRIBUTING.md#docstrings) `Args:` section then serves a model, editors' hovers and `help()` at once.
- **Models describe themselves.** A model's docstring and its fields' `Field(description="...")` are kept: in `input_schema` for an argument, and in `output_schema` for a result. So say what a response's fields mean there, such as which values a status takes. Pydantic leaves out a docstring written under a field unless the model sets `model_config = ConfigDict(use_attribute_docstrings=True)`.
- **The schemas are compact.** Pydantic's `title` on every property is left out, and a model or `type` alias is written in place rather than behind a `$ref`, unless it refers to itself. Constraints, such as `Query(ge=1)`, and defaults are kept.

### Writing descriptions for a model

A model has only the descriptions and the schema to go on, never the code, so write the docstring for a reader who can't see anything else:

- **Start with what the endpoint does,** in one line.
- **In the paragraph after it, say when to use it,** rather than a similar endpoint, and what to expect: side effects, limits, paging, and errors such as a 404 for an unknown ID. Everything before the first section is the tool's description, so `Returns:`, `Raises:` and the other sections don't reach the model: keep nothing it needs there.
- **In `Args:`, give each argument's format, unit and allowed values,** such as an ISO date, seconds, or a maximum.
- **Let the types say what they can.** A `Literal` gives the model the allowed values as a list, and a constraint such as `Query(le=100)` gives it a limit.
- **Markdown is fine,** such as `single backticks` and short lists. Avoid reStructuredText's ` ``double backticks`` ` and `::` blocks, which reach the model as they are.

Before, the model has to guess what `since` takes, which values `status` has, and how this tool differs from others:

```py
@method.get("/orders")
def list_orders(
    self,
    since: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[Order]:
    """Get orders."""
    ...
```

After, the description and the schema answer all three:

```py
@method.get("/orders")
def list_orders(
    self,
    since: Annotated[str | None, Query()] = None,
    status: Annotated[Literal["open", "shipped", "cancelled"] | None, Query()] = None,
) -> list[Order]:
    """List the account's orders, newest first, 50 at most.

    Use `retrieve_order` for one order whose ID you know. Without `since`,
    only the last 30 days are listed.

    Args:
        since: Only orders placed on or after this day, as an ISO date such
            as `2026-01-31`.
        status: Only orders in this state.
    """
    ...
```

## Calling a tool

`tool.call(arguments)` takes the arguments as a model sends them, a mapping from parameter names to JSON values, and returns the result as JSON-ready data, with a model dumped as Pydantic dumps it in JSON mode, by field name:

- Arguments are named as in the method, not by a helper's `alias=`, which is the name sent to the API.
- A model's fields are named as in Python too, in the arguments and in the result, and both schemas list them that way. ClientX still sends and reads the API's names: with `pet_id: int = Field(alias="petId")`, the model sees `pet_id` and the API `petId`.
- They're validated as Pydantic validates a call, leniently: `"7"` fits an `int`.
- Only the arguments the model gave are passed, so the rest keep their defaults, as in a Python call: a `Send(exclude_unset=True)` parameter the model left out isn't sent, and a JSON field left at `None` isn't sent as `null`.

On an `AsyncClientX`, call tools with `await tool.acall(arguments)`. `call()` on an async tool, or `acall()` on a sync one, raises `TypeError`.

## Errors

A call that fails raises `ToolError`, whose message is written for the model, so it can fix its arguments or report the problem. Its `tool` attribute names the tool, and the original error is its `__cause__`, for your logs:

| What went wrong | The message |
|---|---|
| The arguments don't fit | Each argument and its problem, without Pydantic's links: `The arguments don't fit users_search: limit: Input should be less than or equal to 100 (got 500). Nothing was sent.` |
| An argument can't be sent | The [`ArgumentError`](errors.md#argumenterror)'s message, such as an empty path value. |
| A 4xx or 5xx response | The status, the method and path template, and the API's own answer, up to 2,000 characters: `users_create: the API answered 409 Conflict to POST /users: {"detail":"name taken"}` |
| The request failed | The method, the path template and the kind of failure, such as `ConnectTimeout`. |
| The response doesn't fit the return annotation | Each mismatch, without the response's values. |

A message never holds the host or the query string, which can carry credentials from the client's `params=`. Any other exception, such as a decoder's own, or the `RuntimeError` of a closed client, isn't a tool call's failure, and reaches you unchanged.

## Using a framework

Each framework registers tools its own way, but asks for the same things:

- the tool's `name` and `description`;
- its arguments' JSON Schema, `input_schema`, and for structured results, `output_schema`;
- a handler that calls `tool.call(arguments)`, or `await tool.acall(arguments)`, and turns a `ToolError` into an error result with its message;
- for MCP, the hints `read_only`, `destructive` and `idempotent`, as its `readOnlyHint`, `destructiveHint` and `idempotentHint`.

`input_schema` is plain JSON Schema, which each of them takes as it is: only the definition around it differs. A tool's definition for each:

```py
# Anthropic's Messages API
{"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}

# OpenAI's Responses API
{"type": "function", "name": tool.name, "description": tool.description, "parameters": tool.input_schema}

# OpenAI's Chat Completions API
{"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}}

# An MCP tool
{
    "name": tool.name,
    "description": tool.description,
    "inputSchema": tool.input_schema,
    "annotations": {"readOnlyHint": tool.read_only, "destructiveHint": tool.destructive, "idempotentHint": tool.idempotent},
}
```

MCP's `outputSchema` must describe an object, so a tool whose result isn't one, such as a list, needs it wrapped, as `{"result": ...}`, if you give it one.

Strict modes, which constrain the model's arguments to the schema exactly, have rules of their own: OpenAI's needs every property listed in `required`, with optional ones made nullable, and Anthropic's needs `additionalProperties: false` and a `required` list. ClientX doesn't change its schemas for either, so adjust a schema before you turn a strict mode on.

For an MCP server, `clientx.fastmcp` does all of this for [FastMCP](#serving-tools-with-fastmcp).

## Serving tools with FastMCP

[FastMCP](https://gofastmcp.com) is a framework for MCP servers, built on the official MCP SDK. `fastmcp_tool(tool)` turns a ClientX tool into a FastMCP tool, so you can register the ones a model should use on your own server, next to tools of its own. It needs FastMCP, which the `fastmcp` extra installs:

```bash
pip install "clientx[fastmcp]"
```

<!-- docs_src/tools/fastmcp_server.py -->
```python
from typing import Any

from clientx import AsyncClientX, method
from clientx.fastmcp import fastmcp_tool
from clientx.tools import list_tools
from fastmcp import FastMCP


class ShopAPI(AsyncClientX, base_url="https://api.shop.example.com"):
    @method.get("/products/{product_id}")
    async def product(self, product_id: int) -> dict[str, Any]:
        """Fetch a product, with its price and stock."""
        ...

    @method.delete("/orders/{order_id}")
    async def cancel_order(self, order_id: int) -> None:
        """Cancel an order."""
        ...


api = ShopAPI()
# The read-only tools: product, but not cancel_order.
server = FastMCP("shop", tools=[fastmcp_tool(tool) for tool in list_tools(api) if tool.read_only])


@server.tool
def shipping_days(country: str) -> int:
    """Return how many days shipping to a country takes."""
    return 2 if country == "US" else 7


if __name__ == "__main__":
    server.run()  # Over stdio, by default.
```

`product` and `shipping_days` are the server's tools. The server's name, transport, auth and everything else are FastMCP's: see [its docs](https://gofastmcp.com) for serving over HTTP, and [Serving many users](#serving-many-users) for whose credentials a shared client sends.

The FastMCP tool keeps what ClientX describes:

- **Schemas:** the tool's `input_schema` is what the model sees, as it is. FastMCP passes the model's arguments through, and the ClientX tool validates them as `call()` does: leniently, and passing only the arguments the model gave.
- **Results:** a result goes back as structured content, and as text: a string as it is, anything else as JSON. MCP needs an output schema that describes an object, so a result that isn't one, such as a list, is wrapped as `{"result": ...}`, marked as FastMCP marks its own, so FastMCP's client unwraps it.
- **Hints and tags:** `read_only`, `destructive` and `idempotent` become MCP's `readOnlyHint`, `destructiveHint` and `idempotentHint`, and the tool's tags become FastMCP's.
- **Errors:** a `ToolError`'s message reaches the model, as the tool's error. Any other exception, such as a decoder's own, reaches it as a message that names only its type, such as `products failed unexpectedly (RuntimeError).`: FastMCP would otherwise show the exception's message, which can hold a URL or a credential. The original exception is the cause, for the server's logs.
- **Sync clients:** a `ClientX` tool's `call()` runs in a worker thread, so it doesn't block the server. An `AsyncClientX` suits a server best: its calls run on the server's event loop.

## Choosing tools

A model can call any tool you register, so register only what it should use. To choose in the class itself, tag the endpoints a model should use, or a whole resource, and keep the tools with that tag:

<!-- docs_src/tools/choosing_tools.py -->
```python
from typing import Annotated, Any

from clientx import ClientX, Json, Resource, method
from clientx.tools import list_tools


class Products(Resource, prefix="/products", tags=["ai"]):
    @method.post("/search")
    def search(self, query: Annotated[str, Json()]) -> list[dict[str, Any]]:
        """Search the catalog by name or description."""
        ...


class Orders(Resource, prefix="/orders"):
    @method.get("/{order_id}", tags=["ai"])
    def retrieve(self, order_id: int) -> dict[str, Any]:
        """Fetch an order, with its status."""
        ...

    @method.delete("/{order_id}")
    def cancel(self, order_id: int) -> None:
        """Cancel an order."""
        ...


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    products = Products()
    orders = Orders()


api = ShopAPI()
tools = [tool for tool in list_tools(api) if "ai" in tool.tags]  # products_search, orders_retrieve
```

`products_search` is a tool because its resource is tagged, and `orders_retrieve` because it's tagged itself. `orders_cancel` isn't tagged, so it's left out, and so is an endpoint added later to `Orders`, until you tag it.

The hints are another way to choose, as in `[t for t in list_tools(api) if t.read_only]`: see [Hints](#hints).

A deprecated endpoint is still a tool, with its message in `Tool.deprecated`. Leave it out with `[t for t in list_tools(api) if not t.deprecated]`, or keep it: its description tells the model what to use instead.

## Hints

Each tool has three hints about what it does. ClientX doesn't act on them: they're for choosing tools, and for frameworks that show them to a model, such as MCP's tool annotations.

| Hint | Means |
|---|---|
| `read_only` | Calling it changes nothing. |
| `destructive` | It can delete or overwrite what's there. `False` means it only adds. |
| `idempotent` | Calling it again with the same arguments has no further effect. |

### Where each hint comes from

Each of an endpoint's hints is worked out on its own, when the endpoint is defined:

1. **If its `tool_options=` sets the hint,** that's the hint's value.
2. **If it leaves the hint out,** the value comes from the endpoint's HTTP method:

| HTTP method | `read_only` | `destructive` | `idempotent` |
|---|---|---|---|
| `GET`, `HEAD`, `OPTIONS` | `True` | `False` | `True` |
| `POST` | `False` | `False` | `False` |
| `PUT` | `False` | `True` | `True` |
| `PATCH` | `False` | `True` | `False` |
| `DELETE` | `False` | `True` | `True` |

So:

- **An endpoint without `tool_options=`** takes all three hints from its method.
- **An endpoint with `tool_options=`** takes from its method only the hints it leaves out. In `ToolOptions(read_only=True)`, `destructive` and `idempotent` still come from the method.
- **Setting one hint never changes another.** `read_only=False` on a `GET` leaves it idempotent, as `GET` is: set `idempotent=False` too if calling it again has an effect.
- **A [tool method](#tools-that-arent-endpoints) has no HTTP method,** so each hint it leaves out is `False`.

### Setting hints

The HTTP method can be wrong: `POST /search` only reads, and some APIs change something on a `GET`. Set the hints it gets wrong with `tool_options=`:

<!-- docs_src/tools/tool_options.py -->
```python
from typing import Annotated, Any

from clientx import ClientX, Json, Query, method
from clientx.tools import ToolOptions, list_tools


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    @method.post("/search", tool_options=ToolOptions(read_only=True, idempotent=True))
    def search(self, query: Annotated[str, Json()]) -> list[dict[str, Any]]:
        """Search the catalog by name or description."""
        ...

    @method.get("/cart/add", tool_options=ToolOptions(read_only=False, idempotent=False))
    def add_to_cart(self, product_id: Annotated[int, Query()]) -> dict[str, Any]:
        """Add one of a product to the cart."""
        ...


api = ShopAPI()
read_only = [tool for tool in list_tools(api) if tool.read_only]  # search
```

Each tool ends up with these hints:

| Tool | `read_only` | `destructive` | `idempotent` |
|---|---|---|---|
| `search` (`POST`) | `True`, set | `False`, from `POST` | `True`, set |
| `add_to_cart` (`GET`) | `False`, set | `False`, from `GET` | `False`, set |

- `search` only reads, and calling it again changes nothing, so it sets `read_only` and `idempotent`. It leaves out `destructive`, so `POST` gives `False`.
- `add_to_cart` changes the cart, so it sets `read_only=False`. It sets `idempotent=False` too: left out, it would come from `GET`, which is idempotent, and a framework could retry the call and add the product twice. It leaves out `destructive`, so `GET` gives `False`, which is right: it only adds.
- An endpoint can't be read-only and destructive. The check runs on the hints it ends up with, set or from its method, so `ToolOptions(destructive=True)` on a `GET` raises `DefinitionError` when its class is defined: `read_only` comes from `GET`. Set `read_only=False` with it.
- A hint belongs to the endpoint, not to one call. An endpoint that reads or writes depending on an argument, such as `GET /api?action=...`, needs the hints of its riskiest call.

## Tools that aren't endpoints

A model calls one tool at a time, so a task that takes several requests takes it several turns, and it has to piece the answers together itself. Do that work for it in a method of your own, and make the method a tool with `@tool`:

<!-- docs_src/tools/tool_methods.py -->
```python
from clientx import ClientX, method
from clientx.tools import list_tools, tool
from pydantic import BaseModel


class Product(BaseModel):
    id: int
    name: str


class Order(BaseModel):
    id: int
    status: str
    product_ids: list[int]


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    @method.get("/orders/{order_id}")
    def order(self, order_id: int) -> Order:
        """Fetch an order, with the IDs of its products."""
        ...

    @method.get("/products/{product_id}")
    def product(self, product_id: int) -> Product:
        """Fetch a product."""
        ...

    @tool(read_only=True, idempotent=True)
    def order_products(self, order_id: int) -> list[Product]:
        """List the products in an order, in full.

        Args:
            order_id: The order's ID, as on its confirmation.
        """
        order = self.order(order_id)
        return [self.product(product_id) for product_id in order.product_ids]


api = ShopAPI()
print([each.name for each in list_tools(api)])  # ['order', 'product', 'order_products']
```

`list_tools` lists `order_products` with the endpoints, and a model calls it the same way. As for an endpoint, it's named by its attribute path, described by its docstring, and its schemas come from its signature. With one call, the model gets each product in the order, instead of calling `order`, then `product` once per product.

- **It needs a docstring:** that's the tool's description, and there's no method and path to fall back on. It needs a return annotation too, which can't be `bytes`, and each argument and the result need a JSON form: a tool method without one raises `DefinitionError` when you list the tools, rather than being left out, since you made it a tool on purpose.
- **Its hints are `False` unless you set them,** as there's no HTTP method to take them from: `@tool(read_only=True)` is read-only, but neither destructive nor idempotent. They mean what they do for an endpoint (see [Hints](#hints)). Tag it with `@tool(tags=[...])`: a resource's tags go in front, as for an endpoint.
- **It's the kind of its class,** as an endpoint is: `def` on a `ClientX` or `Resource`, and `async def` on an `AsyncClientX` or `AsyncResource`.
- **A request it sends that fails raises `ToolError`,** as for an endpoint (see [Errors](#errors)). The message names only the HTTP method, as in `to a GET request`, since the tool's requests aren't one endpoint's. Other exceptions pass through.
- **An endpoint is a tool already:** `@tool` on one raises `DefinitionError`. Set its hints with `tool_options=` instead.
- **Its name can't be private:** `@tool` on a method whose name starts with `_` raises `DefinitionError`, since `list_tools` would leave it out.

### Guarding an endpoint

Sometimes a request mustn't be sent until something is checked, and the check needs a request of its own. An endpoint's body never runs, so the check can't go there. Put it in a tool method, and give the endpoint it guards a private name, which `list_tools` leaves out:

<!-- docs_src/tools/guard.py -->
```python
from clientx import ArgumentError, ClientX, Resource, method
from clientx.tools import list_tools, tool
from pydantic import BaseModel


class Group(BaseModel):
    id: int
    name: str
    is_default: bool


class Groups(Resource, prefix="/groups"):
    @method.get("/{name}")
    def retrieve(self, name: str) -> Group:
        """Fetch a group, and whether it's the default group."""
        ...

    @method.delete("/{name}")
    def _delete(self, name: str) -> None: ...

    @tool(destructive=True, idempotent=True)
    def delete(self, name: str) -> None:
        """Delete a group, which removes its members from it.

        The default group can't be deleted.
        """
        # The API would delete the default group too, and every user would
        # lose theirs.
        if self.retrieve(name).is_default:
            raise ArgumentError(f"Refused to delete {name!r}: it's the default group.", parameter="name")
        self._delete(name)


class TeamAPI(ClientX, base_url="https://api.team.example.com"):
    groups = Groups()


api = TeamAPI()
print([each.name for each in list_tools(api)])  # ['groups_retrieve', 'groups_delete']
```

A model gets `groups_delete`, the tool method, and never `_delete`, so it can't go around the check. A Python caller calls `api.groups.delete()` and gets the check too. The `ArgumentError` the check raises becomes a `ToolError` whose message the model sees (see [Errors](#errors)), and a Python caller gets the `ArgumentError` itself.

## Serving many users

A tool calls the API through its client, with the client's `auth=`, so one client sends one user's credentials. A server that calls an API for many users, such as a public MCP server, can still use one client: give it an `httpx2.Auth` that sends the credentials of the user whose tool call is running.

Here's a hypothetical flow. You host a public MCP server for a shop's API with [FastMCP](#serving-tools-with-fastmcp), and run your ClientX client behind it:

1. **A user connects** their AI app, such as Claude, to your MCP server.
2. **They sign in through your server's OAuth flow.** Their app gets a token issued for your server. The server's `auth=` validates it on each request, so the server knows who's calling.
3. **They authorize your server with the shop's API.** Your server is an OAuth client of that API, so it gets that user's upstream token, and stores it.
4. **On each tool call, the client's `httpx2.Auth` looks up that user's upstream token,** by the validated token's subject, and the shared client sends it.

Never send the shop's API the token the user's app sent you. It was issued for your server, and the MCP specification forbids [passing it through](https://modelcontextprotocol.io/specification/latest/basic/security_best_practices#token-passthrough): your server's token and the upstream token stay separate. In the sample, that's `caller.token`: use only its `subject`, to find the user's upstream token.

<!-- docs_src/tools/many_users.py -->
```python
from collections.abc import Generator

import httpx2
from clientx import AsyncClientX, method
from clientx.fastmcp import fastmcp_tool
from clientx.tools import list_tools
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel


class Order(BaseModel):
    id: int
    status: str


class ShopAPI(AsyncClientX, base_url="https://api.shop.example.com"):
    @method.get("/orders/{order_id}")
    async def retrieve_order(self, order_id: int) -> Order:
        """Fetch one of the user's orders, with its status."""
        ...


# Each user's upstream token, stored when they authorized your server with the
# shop's API: use a real store.
upstream_tokens: dict[str, str] = {}


class CurrentUserAuth(httpx2.Auth):
    """Send the upstream token of the user whose tool call is running."""

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        # The token the user's app sent your server, which its auth validated.
        caller = get_access_token()
        if caller is None or caller.subject is None:
            raise RuntimeError("No signed-in user: give the server auth=.")
        request.headers["Authorization"] = f"Bearer {upstream_tokens[caller.subject]}"
        yield request


api = ShopAPI(auth=CurrentUserAuth())  # one client and one connection pool, for every user
server = FastMCP(
    "shop",
    auth=JWTVerifier(
        jwks_uri="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="https://mcp.shop.example.com",
    ),
    tools=[fastmcp_tool(tool) for tool in list_tools(api)],
)

if __name__ == "__main__":
    server.run(transport="http")
```

- **Concurrent calls don't mix users.** FastMCP keeps each request's validated token in that request's context, so `get_access_token()` returns the caller of the tool call that's running. Two users calling at once each send their own token, through the same client and its connection pool.
- **Prefer an `AsyncClientX`.** Its calls run on the server's event loop. A sync client works too: `fastmcp_tool` runs its calls in worker threads that keep the request's context.
- **Choose how the server checks tokens in FastMCP.** `JWTVerifier` checks tokens from an identity provider you already use. FastMCP's [docs](https://gofastmcp.com) cover its other ways, such as running the OAuth flow itself.
- **Refresh a token in `auth_flow`.** An `httpx2.Auth` can read the response and send the request again: on a 401, refresh the user's token and retry (see httpx2's [Authentication](https://pydantic.dev/docs/httpx2/advanced/authentication/) documentation). If the refresh fails, the `ToolError`, such as `the API answered 401 Unauthorized`, tells the model to ask the user to connect again.
- **The model never sees a token.** It's only in the request's headers, and a `ToolError` message holds neither headers nor the query string.

Users who differ in more than credentials, such as a base URL per tenant, need separate clients, and each client's `list_tools()` describes its tools again.
