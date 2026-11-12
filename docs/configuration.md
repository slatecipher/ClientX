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
- Any other `httpx2.Client` option, such as `timeout`, `headers`, `auth`, `params`, `transport`, or `follow_redirects`. ClientX passes them to the httpx2 client it creates.

Settings can't be changed afterwards; to use different ones, create another client. Close a client when you're done with it, with a `with` block or `close()`.

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
