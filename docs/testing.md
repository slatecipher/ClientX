# Testing

Test a client without the network by passing an `httpx2.MockTransport` when you create it. The transport calls your handler with each `httpx2.Request` the client sends, and returns the `httpx2.Response` the handler builds, so a test can check what was sent and choose what comes back:

```python
import httpx2
import pytest
from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX, user_agent="users-client/1.0"):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int, fields: str | None = None) -> User:
        """Fetch one user by ID."""
        ...


def test_get_user_sends_the_request_and_decodes_the_user() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    client = UsersAPI("https://api.example.com", transport=httpx2.MockTransport(handler))

    assert client.get_user(42, fields="name") == User(id=42, name="Ada")
    [request] = sent
    assert request.method == "GET"
    assert request.url.path == "/users/42"
    assert request.url.params["fields"] == "name"
    assert request.headers["User-Agent"] == "users-client/1.0"


def test_an_unknown_user_raises() -> None:
    def not_found(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"detail": "Not found"})

    client = UsersAPI("https://api.example.com", transport=httpx2.MockTransport(not_found))

    with pytest.raises(httpx2.HTTPStatusError) as raised:
        client.get_user(7)

    assert raised.value.response.status_code == 404
    assert raised.value.response.json() == {"detail": "Not found"}
```

- `transport=` is an `httpx2.Client` option, so it works with any client. The client builds requests exactly as it would for the real API: the path, query string, headers and body are all there to check.
- Build responses with `httpx2.Response(status, json=...)`, `text=`, `content=` and `headers=`. Decoding and the 4xx and 5xx check run on them as on real responses.
- To test what a JSON body contains, read `json.loads(request.content)`. Form fields are URL-encoded in `request.content`.
- To test a streaming endpoint, give the response an iterator of bytes, such as `content=iter([b"one\n", b"two\n"])`. A `bytes` body is read at once, so it doesn't stream.
- An endpoint's mistakes raise `DefinitionError` when its class is defined, so a test that imports your client module catches them.
- Annotate the handler with types, so the test type-checks in strict mode.
- `httpx2.MockTransport` serves an `AsyncClientX` too, with the same handler: see [Testing](async.md#testing) on the async page.
