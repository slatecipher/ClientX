from typing import Annotated

from clientx import ClientX, method
from pydantic import BaseModel, Field


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...

    @method.get("/users")
    def list_users(self) -> list[User]: ...

    @method.get("/users/count")
    def count_users(self) -> Annotated[int, Field(ge=0)]: ...
