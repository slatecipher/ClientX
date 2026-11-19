from typing import Annotated

from clientx import ClientX, Json, Resource, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def retrieve(self, user_id: int) -> User: ...

    @method.post()
    def create(self, user: Annotated[NewUser, Json()]) -> User: ...


class ExampleAPI(ClientX):
    users = Users()


with ExampleAPI("https://api.example.com") as api:
    user = api.users.retrieve(42)  # GET /users/42
