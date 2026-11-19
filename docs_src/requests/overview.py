from typing import Annotated

from clientx import ClientX, Header, Json, Query, Response, method
from pydantic import BaseModel


class NewPost(BaseModel):
    title: str
    body: str


class PostsAPI(ClientX):
    @method.get("/users/{user_id}/posts")
    def list_posts(
        self,
        user_id: int,
        page: Annotated[int, Query()] = 1,
        tag: Annotated[str | None, Query()] = None,
    ) -> Response: ...

    @method.post("/posts")
    def create_post(
        self,
        post: Annotated[NewPost, Json()],
        request_id: Annotated[str, Header()],
    ) -> Response: ...
