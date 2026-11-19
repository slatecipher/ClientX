import httpx2
import pytest
from clientx import AsyncClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(AsyncClientX):
    @method.get("/users/{user_id}")
    async def get_user(self, user_id: int) -> User: ...


@pytest.mark.anyio
async def test_get_user_decodes_the_user() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": 42, "name": "Ada"})

    async with UsersAPI("https://api.example.com", transport=httpx2.MockTransport(handler)) as api:
        assert await api.get_user(42) == User(id=42, name="Ada")
