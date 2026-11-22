from typing import Annotated

from clientx import ArgumentError, ClientX, Query, method


class ExampleAPI(ClientX, base_url="https://api.example.com"):
    @method.get("/users")
    def list_users(self, page: Annotated[int, Query(ge=1)] = 1) -> None: ...


with ExampleAPI(validate_arguments=True) as api:
    try:
        api.list_users(page=0)
    except ArgumentError as error:
        print(error.parameter)  # page: no request was sent
