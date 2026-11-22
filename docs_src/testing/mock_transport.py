from typing import Annotated

import httpx2
import pytest
from clientx import ClientX, Query, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX, user_agent="users-client/1.0"):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int, fields: Annotated[str | None, Query()] = None) -> User:
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
    assert request.headers["User-Agent"].startswith("users-client/1.0")


def test_an_unknown_user_raises() -> None:
    def not_found(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"detail": "Not found"})

    client = UsersAPI("https://api.example.com", transport=httpx2.MockTransport(not_found))

    with pytest.raises(httpx2.HTTPStatusError) as raised:
        client.get_user(7)

    assert raised.value.response.status_code == 404
    assert raised.value.response.json() == {"detail": "Not found"}
