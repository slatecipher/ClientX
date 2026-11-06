# pyright: reportUnnecessaryTypeIgnoreComment=true, reportUntypedFunctionDecorator=true
"""Static typing contract for decorated endpoints and decoders.

Pyright checks this file in the blocking ``make typecheck`` step, so it fails CI
if the typing contract regresses:

- ``reportUntypedFunctionDecorator`` is enabled because pyright otherwise hides an
  untyped decorator by falling back to the undecorated signature. mypy has no such
  fallback and would see every endpoint as ``Any``.
- ``assert_type`` fails if the inferred type is not exactly the expected one.
- Each ``# pyright: ignore[...]`` comment is an expected error. The file-level
  ``reportUnnecessaryTypeIgnoreComment`` setting turns an unused ignore into an
  error, so code that should be rejected but is accepted is reported.

The tests also run under pytest against a mock transport.
"""

from collections.abc import Iterator
from typing import Any, assert_type

import httpx2
import pytest
from pydantic import BaseModel, TypeAdapter

from clientx import ClientX, Response
from clientx.decoders import ModelDecoder, StreamLinesDecoder, TypeAdapterDecoder, json_decoder, text_decoder
from clientx.exceptions import MissingDecoderError
from clientx.methods import delete, get, post


class User(BaseModel):
    name: str


class ItemsClient(ClientX):
    @get("/items/{item_id}")
    def get_item(self, item_id: str) -> Response: ...

    @post("/items", decoder=json_decoder)
    def create_item(self, json: dict[str, object]) -> Any: ...

    @delete("/items/{item_id}")
    def delete_item(self, item_id: str) -> None: ...


class UsersClient(ClientX):
    @get("/users/{user_id}", decoder=ModelDecoder(User))
    def get_user(self, user_id: str) -> User: ...

    @get("/users", decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def list_users(self) -> list[User]: ...

    @get("/users/{user_id}/bio", decoder=text_decoder)
    def get_bio(self, user_id: str) -> str: ...

    @get("/users/events", decoder=StreamLinesDecoder())
    def events(self) -> Iterator[str]: ...

    # The decoder produces a User, so declaring a str return is rejected.
    @get("/users/{user_id}/name", decoder=ModelDecoder(User))  # pyright: ignore[reportArgumentType]
    def get_user_name(self, user_id: str) -> str: ...


def _transport() -> httpx2.MockTransport:
    payloads: dict[str, object] = {
        "/users/1": {"name": "Ada"},
        "/users": [{"name": "Ada"}],
    }
    return httpx2.MockTransport(lambda request: httpx2.Response(200, json=payloads.get(request.url.path, {"ok": True})))


def test_decorated_methods_keep_their_declared_types() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    assert_type(client.get_item("1"), Response)
    assert_type(client.get_item(item_id="1"), Response)
    assert_type(client.create_item({"name": "x"}), Any)
    assert_type(client.delete_item("1"), None)


def test_decorated_methods_reject_wrong_arguments() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    client.get_item(1)  # pyright: ignore[reportArgumentType]
    client.create_item(json="not a dict")  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        client.delete_item()  # pyright: ignore[reportCallIssue]


def test_decoded_methods_return_the_decoder_output_type() -> None:
    client = UsersClient("https://example.test", transport=_transport())

    assert_type(client.get_user("1"), User)
    assert_type(client.list_users(), list[User])
    assert_type(client.get_bio("1"), str)
    assert_type(client.events(), Iterator[str])


def test_decoders_called_directly_return_the_decoded_type() -> None:
    response = httpx2.Response(200, json=[{"name": "Ada"}])

    assert_type(ModelDecoder(User)(httpx2.Response(200, json={"name": "Ada"})), User)
    assert_type(TypeAdapterDecoder(TypeAdapter(list[User]))(response), list[User])


def test_methods_without_decoder_must_return_response_or_none() -> None:
    with pytest.raises(MissingDecoderError):

        class Broken(ClientX):
            @get("/users/{user_id}")  # pyright: ignore[reportArgumentType]
            def get_user(self, user_id: str) -> User: ...
