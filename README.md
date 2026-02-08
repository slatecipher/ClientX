# ClientX

Typed, declarative HTTP API clients for Python 3.12+.

ClientX turns endpoint method signatures into HTTP requests, validates responses
with Pydantic, and keeps your client implementation minimal and readable.

## Features

- Declarative endpoints using `@api.get`, `@api.post`, etc.
- Typed response decoding with Pydantic models or TypeAdapter.
- Automatic path parameter injection from method arguments.
- Request body/params/headers/files mapping via `Annotated` or Pydantic models.
- Optional deprecation warnings per endpoint.

## Install

```bash
pip install clientx
```

## Quickstart

```python
from clientx import ClientX, Response, api


class Users(ClientX):
    @api.get("/users/{user_id}")
    def get_user(self, user_id: str) -> Response:
        # Body never executes; ClientX builds and sends the request
        ...


client = Users.setup_client("https://api.example.com")
response = client.get_user("42")
print(response.status_code)
```

## Typed responses

If the return type is neither `Response` nor `None`, a decoder is required.

```python
from pydantic import BaseModel
from clientx import ClientX, api, ModelDecoder


class User(BaseModel):
    id: int
    email: str


class Users(ClientX):
    @api.get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: str) -> User:
        ...
```

## Request payload mapping

ClientX builds requests from method arguments.

### `Annotated` request parts

```python
from typing import Annotated
from clientx import ClientX, api
from clientx.request_factory import ReqPart


class Search(ClientX):
    @api.get("/search")
    def search(
        self,
        q: Annotated[str, ReqPart.PARAMS],
        token: Annotated[str, ReqPart.HEADERS],
    ) -> None:
        ...
```

### Pydantic request models

```python
from typing import Annotated
from pydantic import BaseModel, Field
from clientx.request_factory import ReqPart


class Payload(BaseModel):
    token: Annotated[str, ReqPart.HEADERS]
    q: Annotated[str, ReqPart.PARAMS]
    data: Annotated[str, ReqPart.JSON] = Field(alias="payload")
```

Passing `Payload(...)` as an endpoint argument will route fields into
headers/params/json automatically. Remaining fields default to JSON.

## Deprecation warnings

```python
from clientx import ClientX, Response, Deprecated, api


class Example(ClientX):
    @api.get(
        "/old",
        deprecated=Deprecated("Deprecated: use /new instead."),
    )
    def old(self) -> Response:
        ...
```

## Using TypeAdapter decoders

```python
from pydantic import TypeAdapter
from clientx import ClientX, api, TypeAdapterDecoder

UsersAdapter = TypeAdapter(list[str])


class Example(ClientX):
    @api.get("/users", decoder=TypeAdapterDecoder(UsersAdapter))
    def list_users(self) -> list[str]:
        ...
```

## How it works

- Client methods are wrapped at definition time.
- When you call an endpoint:
  - Path parameters are filled from arguments.
  - Request parts (params/json/headers/files/data) are built from arguments.
  - The request is sent via `httpx.Client`.
  - The response is returned or decoded based on the return type.

## Development

```bash
pytest
ruff check .
```

## Notes / Limitations

- Sync-only (`httpx.Client`); no async client yet.
- Decoder is required for non-`Response` return types.
- Default user agent is `ClientX/<version>`, or override via `setup_client`.
