from typing import Annotated

from clientx import ClientX, Header, Query, Response, method

type UserId = Annotated[int, Query(alias="userId")]
type HeaderValue[T] = Annotated[T, Header()]


class PostsAPI(ClientX):
    @method.get("/posts")
    def list_posts(self, user_id: UserId, trace_id: HeaderValue[str | None] = None) -> Response: ...
