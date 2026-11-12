from typing import Annotated

from pydantic import Field, TypeAdapter

from clientx import Body, ClientX, DumpConfig, PathParam, Query, Resource, methods
from clientx.decoders import ModelDecoder, TypeAdapterDecoder

from .jsonplaceholder_models import Comment, NewPost, Post, PostChanges, User

JSONPLACEHOLDER_URL = "https://jsonplaceholder.typicode.com"

# Path parameters are matched to their `{placeholder}` by name; PathParam() only describes them, for
# the AI tool schemas. Each helper (Query, Header, ...) takes `description=` the same way.
# Field's bounds go into those schemas too (tool calls are checked against them), and direct calls
# check them when argument validation is on. The upper bounds fit JSONPlaceholder's fixed fake data
# (100 posts, 10 users); a real API's IDs keep growing, so a real client would set only ge=1.
PostId = Annotated[int, PathParam(description="The post's ID."), Field(ge=1, le=100)]
UserId = Annotated[int, PathParam(description="The user's ID."), Field(ge=1, le=10)]


# The endpoints use `@methods.get(...)`, not `@get(...)`: a method named `get` would hide the decorator
# for the rest of the class body. The same goes for `list`: no later annotation here uses `list[...]`.
class Posts(Resource, prefix="/posts", tags=["posts"]):
    @methods.get(decoder=TypeAdapterDecoder(TypeAdapter(list[Post])))
    def list(
        self,
        # Sent as `?userId=...`, and left out when it's None.
        user_id: Annotated[int | None, Query("userId", description="Only list posts by this user.")] = None,
    ) -> list[Post]:
        """List blog posts. Without user_id, returns all 100 posts."""
        ...

    @methods.get("/{post_id}", decoder=ModelDecoder(Post))
    def get(self, post_id: PostId) -> Post:
        """Fetch one blog post by its ID."""
        ...

    @methods.post(decoder=ModelDecoder(Post))
    def create(self, post: NewPost) -> Post:
        """Create a blog post and return it with its new ID. JSONPlaceholder is fake: the post isn't saved."""
        ...

    @methods.put("/{post_id}", decoder=ModelDecoder(Post))
    def replace(self, post_id: PostId, post: NewPost) -> Post:
        """Replace all of a blog post's content and return the result. JSONPlaceholder is fake: nothing is saved."""
        ...

    @methods.patch("/{post_id}", decoder=ModelDecoder(Post))
    def update(
        self,
        post_id: PostId,
        # `exclude_unset` sends only the fields the caller set, not nulls for the rest.
        changes: Annotated[PostChanges, Body(dump_config=DumpConfig(exclude_unset=True))],
    ) -> Post:
        """Change some of a blog post's fields and return the result. JSONPlaceholder is fake: nothing is saved."""
        ...

    @methods.delete("/{post_id}")
    def delete(self, post_id: PostId) -> None:
        """Delete a blog post. JSONPlaceholder is fake: the post isn't really deleted."""
        ...


class Comments(Resource, prefix="/posts/{post_id}/comments", tags=["comments"]):
    @methods.get(decoder=TypeAdapterDecoder(TypeAdapter(list[Comment])))
    def list(self, post_id: PostId) -> list[Comment]:
        """List the comments left on one blog post."""
        ...


class Users(Resource, prefix="/users", tags=["users"]):
    @methods.get(decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def list(self) -> list[User]:
        """List all 10 users, with their contact details, address and company."""
        ...

    @methods.get("/{user_id}", decoder=ModelDecoder(User))
    def get(self, user_id: UserId) -> User:
        """Fetch one user by ID, with their contact details, address and company."""
        ...


class JSONPlaceholder(ClientX):
    """Client for JSONPlaceholder (https://jsonplaceholder.typicode.com), a free fake REST API.

    Writes (create, replace, update, delete) return realistic responses but change nothing on the server.
    A 4xx or 5xx response, such as a 404 for a post that doesn't exist, raises `httpx2.HTTPStatusError`.
    """

    posts = Posts()
    comments = Comments()
    users = Users()
