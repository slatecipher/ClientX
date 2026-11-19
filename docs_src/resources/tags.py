from clientx import Resource, method


class Users(Resource, prefix="/users", tags=["users"]):
    @method.get("/{user_id}", tags=["read"])
    def retrieve(self, user_id: int) -> None: ...


class Admins(Users, tags=["admin"]):
    @method.post("/{user_id}/promote", tags=["write"])
    def promote(self, user_id: int) -> None: ...
