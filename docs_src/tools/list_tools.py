from typing import Annotated

from clientx import ClientX, Json, Query, Resource, method
from clientx.tools import ToolError, list_tools
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class NewUser(BaseModel):
    name: str


class Users(Resource, prefix="/users"):
    @method.get()
    def search(self, name: Annotated[str | None, Query(description="Only users with this name.")] = None) -> list[User]:
        """List users."""
        ...

    @method.post()
    def create(self, user: Annotated[NewUser, Json()]) -> User:
        """Create a user.

        Args:
            user: The user to create. Its name must be unique.
        """
        ...


class ExampleAPI(ClientX, base_url="https://api.example.com"):
    users = Users()


api = ExampleAPI()
tools = {tool.name: tool for tool in list_tools(api)}  # users_search, users_create
create = tools["users_create"]
print(create.description)  # Create a user.
print(create.input_schema)  # {"properties": {"user": {"description": "The user to create. ...", ...}}, ...}

try:
    user = create.call({"user": {"name": "Ada"}})  # {"id": 1, "name": "Ada"}
except ToolError as error:
    print(error)  # users_create: the API answered 409 Conflict to POST /users: {"detail":"name taken"}
