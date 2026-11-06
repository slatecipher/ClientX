# pyright: reportUnnecessaryTypeIgnoreComment=true, reportUntypedFunctionDecorator=true
"""Static typing contract for decorated endpoints.

Pyright checks this file in the blocking ``make typecheck`` step, so it fails CI
if decorated methods stop exposing their declared signatures:

- ``reportUntypedFunctionDecorator`` is enabled because pyright otherwise hides an
  untyped decorator by falling back to the undecorated signature. mypy has no such
  fallback and would see every endpoint as ``Any``.

- ``assert_type`` fails if the inferred return type is not exactly the declared one.
- Each ``# pyright: ignore[...]`` comment is an expected error. The file-level
  ``reportUnnecessaryTypeIgnoreComment`` setting turns an unused ignore into an
  error, so a call that should be rejected but is accepted (because the signature
  was erased to ``Any``) is reported.

The tests also run under pytest against a mock transport.
"""

from typing import assert_type

import httpx2
import pytest

from clientx import ClientX, Response
from clientx.decoders import json_decoder
from clientx.methods import delete, get, post


class ItemsClient(ClientX):
    @get("/items/{item_id}")
    def get_item(self, item_id: str) -> Response: ...

    @post("/items", decoder=json_decoder)
    def create_item(self, json: dict[str, object]) -> dict[str, object]: ...

    @delete("/items/{item_id}")
    def delete_item(self, item_id: str) -> None: ...


def _transport() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda request: httpx2.Response(200, json={"ok": True}))


def test_decorated_methods_keep_their_declared_types() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    assert_type(client.get_item("1"), Response)
    assert_type(client.get_item(item_id="1"), Response)
    assert_type(client.create_item({"name": "x"}), dict[str, object])
    assert_type(client.delete_item("1"), None)


def test_decorated_methods_reject_wrong_arguments() -> None:
    client = ItemsClient("https://example.test", transport=_transport())

    client.get_item(1)  # pyright: ignore[reportArgumentType]
    client.create_item(json="not a dict")  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        client.delete_item()  # pyright: ignore[reportCallIssue]
