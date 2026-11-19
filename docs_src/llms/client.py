from typing import Annotated

from clientx import ClientX, Header, Json, Query, Resource, Response, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get()
    def search(
        self,
        name: Annotated[str, Query(alias="q")],
        limit: Annotated[int | None, Query()] = None,
    ) -> list[User]:
        """Search users by name."""
        ...

    @method.post()
    def create(
        self,
        user: Annotated[NewUser, Json()],
        request_id: Annotated[str | None, Header()] = None,
    ) -> User:
        """Create a user."""
        ...

    @method.patch("/{user_id}")
    def rename(self, user_id: int, changes: Annotated[dict[str, str], Json()]) -> User:
        """Change some of a user's fields."""
        ...

    @method.delete("/{user_id}")
    def remove(self, user_id: int) -> None:
        """Delete a user."""
        ...


class ExampleAPI(ClientX, user_agent="example-app/1.0"):
    users = Users()

    @method.get("/health")
    def health(self) -> Response:
        """Check the service."""
        ...


# A 4xx or 5xx response raises httpx2.HTTPStatusError from any endpoint (raise_for_status=False turns it off).
with ExampleAPI("https://api.example.com", auth=("user", "secret"), timeout=10.0) as api:
    user = api.users.retrieve(42)  # GET /users/42 -> User
    matches = api.users.search("Ada")  # GET /users?q=Ada -> list[User] (limit is None, so it's left out)
    api.users.create(NewUser(name="Ada"), request_id="r-1")  # POST /users, JSON {"name":"Ada"}, header request-id
    api.users.rename(42, {"name": "Ada L."})  # PATCH /users/42 with JSON {"name":"Ada L."}
