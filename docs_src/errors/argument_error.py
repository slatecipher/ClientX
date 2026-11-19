from clientx import ArgumentError, ClientX, method


class UsersAPI(ClientX):
    @method.get("/users/{user_id}")
    def get_user(self, user_id: str) -> None: ...


with UsersAPI("https://api.example.com") as api:
    try:
        api.get_user("")
    except ArgumentError as error:
        print(error.parameter)  # user_id: no request was sent
