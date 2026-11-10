from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class JSONPlaceholderModel(BaseModel):
    """Base model: snake_case in Python, camelCase (`userId`, `postId`) on the wire.

    ClientX sends request models by alias, so `NewPost(user_id=1)` goes out as `{"userId": 1}`.
    `validate_by_name` lets you build models with the snake_case names.
    """

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


class Post(JSONPlaceholderModel):
    """A blog post written by a user."""

    id: int = Field(description="The post's ID.")
    user_id: int = Field(description="The ID of the user who wrote the post.")
    title: str = Field(description="The post's title.")
    body: str = Field(description="The post's text.")


class NewPost(JSONPlaceholderModel):
    """The content of a post, used to create a post or replace all of an existing one."""

    user_id: int = Field(description="The ID of the user who writes the post.")
    title: str = Field(description="The post's title.")
    body: str = Field(description="The post's text.")


class PostChanges(JSONPlaceholderModel):
    """Changes to some of a post's fields. Fields left out stay as they are."""

    user_id: int | None = Field(default=None, description="The ID of the user who writes the post.")
    title: str | None = Field(default=None, description="The post's new title.")
    body: str | None = Field(default=None, description="The post's new text.")


class Comment(JSONPlaceholderModel):
    """A comment left on a post."""

    id: int = Field(description="The comment's ID.")
    post_id: int = Field(description="The ID of the post the comment belongs to.")
    name: str = Field(description="The comment's title.")
    email: str = Field(description="The commenter's email address.")
    body: str = Field(description="The comment's text.")


class Geo(JSONPlaceholderModel):
    """Geographic coordinates."""

    lat: str = Field(description="Latitude.")
    lng: str = Field(description="Longitude.")


class Address(JSONPlaceholderModel):
    """A postal address."""

    street: str
    suite: str
    city: str
    zipcode: str
    geo: Geo


class Company(JSONPlaceholderModel):
    """The company a user works for."""

    name: str
    catch_phrase: str
    bs: str = Field(description="The company's business slogan.")


class User(JSONPlaceholderModel):
    """A user who writes posts."""

    id: int = Field(description="The user's ID.")
    name: str = Field(description="The user's full name.")
    username: str
    email: str
    address: Address
    phone: str
    website: str
    company: Company
