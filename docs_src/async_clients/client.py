import asyncio
from typing import Annotated

from clientx import AsyncClientX, AsyncResource, Query, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(AsyncResource, prefix="/users"):
    @method.get("/{user_id}")
    async def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get()
    async def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(AsyncClientX, user_agent="example-app/1.0"):
    users = Users()


async def main() -> None:
    async with ExampleAPI("https://api.example.com") as api:
        user = await api.users.retrieve(42)  # GET /users/42, decoded into a User
        # Several requests at once, sharing the client's connections:
        ada, grace = await asyncio.gather(api.users.retrieve(1), api.users.retrieve(2))
        print(user.name, ada.name, grace.name)


asyncio.run(main())
