from typing import Annotated

from clientx import ClientX, Query, Resource, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get()
    def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(ClientX, user_agent="example-app/1.0"):
    users = Users()


with ExampleAPI("https://api.example.com") as api:
    user = api.users.retrieve(42)  # GET /users/42 -> User
    matches = api.users.search(name="Ada")  # GET /users?name=Ada -> list[User]
