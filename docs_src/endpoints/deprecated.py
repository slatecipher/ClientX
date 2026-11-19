from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/v1/users/{user_id}", deprecated="Use get_user() instead.")
    def get_user_v1(self, user_id: int) -> User: ...

    @method.get("/v2/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...
