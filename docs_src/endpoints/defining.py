from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...


with UsersAPI("https://api.example.com") as api:
    user = api.get_user(42)  # GET /users/42, decoded into a User
