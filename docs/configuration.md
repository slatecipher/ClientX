# Client Configuration

Configure a client when you create it:

```python
from clientx import ClientX


class ExampleAPI(ClientX):
    ...


api = ExampleAPI("https://api.example.com", user_agent="my-app/1.0", timeout=5.0)
```

- `base_url`: the API's base URL. Optional when the class sets one (see below).
- `user_agent`: the `User-Agent` to send. Without it, the first of these is sent: a `User-Agent` in `headers=`, the class's `user_agent=`, or `ClientX/<version>`.
- `raise_for_status` and `validate_arguments`: see [Raising errors for 4xx and 5xx responses](#raising-errors-for-4xx-and-5xx-responses) and [Validating arguments](#validating-arguments) below.
- Any other `httpx2.Client` option, such as `timeout`, `headers`, `auth` (see [Authentication](#authentication)), `params`, `transport`, or `follow_redirects`. ClientX passes them to the httpx2 client it creates.

Settings can't be changed afterwards; to use different ones, create another client. Instances are independent: each has its own connections, settings, and credentials, so clients for production and staging, or one client per account, can be used side by side. Class arguments (below) are only defaults for new instances.

A client class can ship its own base URL and `User-Agent` as class arguments, so callers can create it without arguments:

```python
from clientx import ClientX


class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-api/1.0"):
    ...


api = ExampleAPI()  # https://api.example.com, User-Agent: example-api/1.0
staging = ExampleAPI("https://staging.example.com", timeout=10.0)  # arguments given here win
```

A subclass keeps its parent's class arguments unless it sets its own. Without a base URL in the class or in the call, creating the client raises `TypeError`.

`base_url` and `user_agent` are the only class arguments. Pass every other option, such as `timeout=` or `transport=`, when creating the client. Python rejects any other keyword in the class statement, a misspelling included, with `TypeError: ExampleAPI.__init_subclass__() takes no keyword arguments`.

## Authentication

Give a client its credentials with `auth=` when you create it. `auth=` is httpx2's authentication option: ClientX passes it to the httpx2 client, which applies it to every request. For what it accepts and how to write your own scheme, see httpx2's [Authentication](https://pydantic.dev/docs/httpx2/advanced/authentication/) documentation.

Keep credentials out of endpoint parameters: every caller would have to pass them, and when endpoints are [AI tools](ai-tools.md), parameters are what the model sees and fills in.

### Getting a token with a client ID and secret

Many APIs want a short-lived bearer token from a token endpoint, which you get with a client ID and secret: OAuth 2's client credentials grant. An `Auth` subclass can do this itself. Its `auth_flow` method is a generator that yields each request to send and receives the response. It can yield a token request before the original request, and send the original request again after a 401. httpx2 sends all of them through the client, with its transport and settings.

```python
import math
import os
import time
from base64 import b64encode
from collections.abc import Generator
from urllib.parse import quote_plus

from clientx import Auth, ClientX, Request, Response


class ClientCredentials(Auth):
    """OAuth 2 client credentials: get a bearer token with a client ID and secret, and send it with every request."""

    requires_response_body = True  # The flow reads the token response's JSON.

    def __init__(self, token_url: str, client_id: str, client_secret: str, scope: str | None = None) -> None:
        self.token_url = token_url
        self.scope = scope
        # RFC 6749, section 2.3.1: form-encode the ID and secret, then send them with HTTP Basic authentication.
        credentials = f"{quote_plus(client_id)}:{quote_plus(client_secret)}"
        self.client_authorization = f"Basic {b64encode(credentials.encode()).decode()}"
        self.access_token = ""
        self.expires_at = 0.0

    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        if time.monotonic() >= self.expires_at:
            yield from self.fetch_token()
        request.headers["Authorization"] = f"Bearer {self.access_token}"
        response = yield request
        if response.status_code == 401:
            yield from self.fetch_token()
            request.headers["Authorization"] = f"Bearer {self.access_token}"
            yield request

    def fetch_token(self) -> Generator[Request, Response, None]:
        data = {"grant_type": "client_credentials"}
        if self.scope:
            data["scope"] = self.scope
        headers = {"Authorization": self.client_authorization}
        response = yield Request("POST", self.token_url, data=data, headers=headers)
        response.raise_for_status()
        token = response.json()
        self.access_token = token["access_token"]
        # Renew 30 seconds early, so the token can't expire on its way. Without expires_in (it's optional),
        # keep the token until the API rejects it.
        lifetime = token.get("expires_in")
        self.expires_at = math.inf if lifetime is None else time.monotonic() + lifetime - 30


class ExampleAPI(ClientX):
    ...


# Read the ID and secret from the environment or a secrets manager, never from your source code.
auth = ClientCredentials("https://auth.example.com/oauth/token", os.environ["CLIENT_ID"], os.environ["CLIENT_SECRET"])
api = ExampleAPI("https://api.example.com", auth=auth)
```

- The first call gets a token, and later calls reuse it until it expires. If the API rejects it sooner with a 401, the request is sent again once, with a new token.
- A failed token request, such as one with a wrong secret, raises `httpx2.HTTPStatusError` with the token endpoint's response, for example `400 {"error": "invalid_client"}`. The API request isn't sent.
- With `requires_response_body = True`, httpx2 reads every response before returning it, not only the token response. On this client, a [streaming endpoint](decoders.md#streaming-responses) still works, but its response is read in full first.
- Threads that share the client share its token. Two of them can get a new token at the same time, which costs an extra token request. To avoid that, use a lock, as httpx2's documentation shows.
- [`examples/oauth2/`](https://github.com/slatecipher/ClientX/tree/mainline/examples/oauth2) runs this class against Duende's public demo server.

Don't add credentials in a request [event hook](logging.md#your-own-request-logging). httpx2 documents hooks for logging, monitoring, and tracing. A request hook also runs again for every redirect, so it would put back an `Authorization` header that httpx2 dropped for another host. And it can't send a token request through the client's flow or send a request again after a 401.

For other schemes, httpx2's [Third Party Packages](https://pydantic.dev/docs/httpx2/community/third_party_packages/) page lists libraries that support it. ClientX creates its own httpx2 client, so use a library's `Auth` class as `auth=`, not its client class.

## Closing a client

Close a client when you're done with it, to release its connections:

- For a script or one batch of calls, use a `with` block, as the README's quickstart does. It closes the client when the block ends, even if an exception is raised.
- For a long-lived client, such as one in a web app or a worker, create it once, reuse it for every request so its connections are pooled, and call `close()` at shutdown. Don't create a client for each request.
- A closed client can't be reused: a call raises `RuntimeError: Cannot send a request, as the client has been closed.` Create a new one.
- `with` is optional. A client that's never closed still works; its connections stay open until the process exits or the client is garbage-collected.

## Raising errors for 4xx and 5xx responses

A 4xx or 5xx response raises `httpx2.HTTPStatusError`, from every endpoint, before any decoder runs. The error has the request and the response, and the body is already read, so `exc.response.json()` works:

```python
import httpx2
from clientx import ClientX
from clientx.decoders import ModelDecoder
from clientx.methods import get
from pydantic import BaseModel


class User(BaseModel):
    id: int


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: int) -> User:
        ...


with UsersClient("https://api.example.com") as client:
    try:
        client.get_user(1000)
    except httpx2.HTTPStatusError as exc:
        print(exc.response.status_code, exc.response.json())  # for example: 404 {"error": "not found"}
```

- Redirects aren't errors. With `follow_redirects=True`, only the final response is checked; without it, a 3xx response is returned as it is.
- For a streaming endpoint, an error response is read and closed before the error is raised, so its connection is released. A successful one still streams.
- Endpoints called as AI tools raise it too. Over MCP, it comes back to the model as an error result.

Turn it off for a whole client with `raise_for_status=False`, or set it per endpoint. An endpoint's setting wins over the client's:

```python
from clientx import ClientX, Response
from clientx.methods import get


class FilesClient(ClientX):
    @get("/files/{name}", raise_for_status=False)
    def get_file(self, name: str) -> Response:
        """Return a 404 as a response instead of raising it, so the caller can check `status_code`."""
        ...


client = FilesClient("https://api.example.com")  # every other endpoint still raises
unchecked = FilesClient("https://api.example.com", raise_for_status=False)  # no endpoint raises
```

With the check off, a decoder gets every response, so it can handle error statuses itself.

## Validating arguments

Type checkers catch wrong argument types in your own code, but not in values that arrive at run time, such as user input or data from another service. Turn on `validate_arguments` to check each argument against its parameter's annotation before the request is sent:

```python
from typing import Annotated

from clientx import ClientX, Query, Response
from clientx.exceptions import ArgumentValidationError
from clientx.methods import get
from pydantic import Field


class SearchClient(ClientX):
    @get("/search")
    def search(self, page: Annotated[int, Query(), Field(ge=1)]) -> Response: ...


client = SearchClient("https://api.example.com", validate_arguments=True)

try:
    client.search(0)
except ArgumentValidationError as exc:
    print(exc.parameter)  # page: no request was sent
```

- It's off by default. Turn it on for a whole client with `validate_arguments=True`, or set it per endpoint with the decorators' `validate_arguments=` option. An endpoint's setting wins over the client's.
- The check is strict, like a type checker's: `"1"` doesn't match `int`, and a string doesn't match an `Enum`. Values are never converted, so a request is the same with validation on or off. Constraints in the annotation, such as `Field(ge=1)`, are checked too.
- To normalize a value instead of rejecting it, such as lowercasing a name, call the endpoint from a [plain method](resources.md#plain-methods) that changes the value first.
- Only the arguments the caller passes are checked, not defaults.
- A parameter whose type Pydantic can't validate, such as `BinaryIO`, isn't checked. Neither is a parameter without an annotation.
- `ArgumentValidationError` has the `parameter` name and Pydantic's error as `validation_error`. It's a `ClientXError` and a `ValueError`.
- `Tool.call()` already validates a model's arguments, and converts JSON values such as `"red"` to the parameter's type, so tool calls pass this check.
