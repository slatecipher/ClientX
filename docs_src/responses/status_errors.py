import httpx2
from clientx import ClientX, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: int) -> User: ...


with UsersAPI("https://api.example.com") as api:
    try:
        api.get_user(1000)
    except httpx2.HTTPStatusError as error:
        print(error.response.status_code, error.response.json())  # for example: 404 {'detail': 'Not found'}
