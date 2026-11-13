"""An async client for JSONPlaceholder, for asyncio code and concurrent requests.

It has the read-only endpoints of `jsonplaceholder_client.py` as `async def` methods, on `AsyncResource`
classes mounted on an `AsyncClientX`, and shares that module's models and annotations.
"""

from typing import Annotated

from clientx import AsyncClientX, AsyncResource, Query, methods
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from pydantic import TypeAdapter

from .jsonplaceholder_client import JSONPLACEHOLDER_URL, PostId, UserId
from .jsonplaceholder_models import Comment, Post, User


# As in jsonplaceholder_client.py, `@methods.get(...)`, because endpoints named `get` and `list` would hide
# the decorator and the built-in for the rest of the class body.
class AsyncPosts(AsyncResource, prefix="/posts", tags=["posts"]):
    @methods.get(decoder=TypeAdapterDecoder(TypeAdapter(list[Post])))
    async def list(
        self,
        user_id: Annotated[int | None, Query("userId", description="Only list posts by this user.")] = None,
    ) -> list[Post]:
        """List blog posts. Without user_id, returns all 100 posts."""
        ...

    @methods.get("/{post_id}", decoder=ModelDecoder(Post))
    async def get(self, post_id: PostId) -> Post:
        """Fetch one blog post by its ID."""
        ...


class AsyncComments(AsyncResource, prefix="/posts/{post_id}/comments", tags=["comments"]):
    @methods.get(decoder=TypeAdapterDecoder(TypeAdapter(list[Comment])))
    async def list(self, post_id: PostId) -> list[Comment]:
        """List the comments left on one blog post."""
        ...


class AsyncUsers(AsyncResource, prefix="/users", tags=["users"]):
    @methods.get("/{user_id}", decoder=ModelDecoder(User))
    async def get(self, user_id: UserId) -> User:
        """Fetch one user by ID, with their contact details, address and company."""
        ...


class AsyncJSONPlaceholder(AsyncClientX, base_url=JSONPLACEHOLDER_URL, user_agent="jsonplaceholder-example/0.1"):
    """Async client for JSONPlaceholder (https://jsonplaceholder.typicode.com): await each endpoint.

    A 4xx or 5xx response, such as a 404 for a post that doesn't exist, raises `httpx2.HTTPStatusError`.
    """

    posts = AsyncPosts()
    comments = AsyncComments()
    users = AsyncUsers()
