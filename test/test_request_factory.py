import inspect
from enum import StrEnum
from typing import Annotated, cast

import pytest
from pydantic import BaseModel, Field

from clientx._annotations import DumpConfig, FieldX, RequestPart
from clientx._client import ClientX
from clientx._endpoint_context import Endpoint
from clientx._request_factory import ArgumentCursor, ModelExtractor, RequestFactory
from clientx.exceptions import UnconsumableArgumentError


class Payload(BaseModel):
    headers: Annotated[dict[str, str], FieldX(RequestPart.HEADERS)]
    params: Annotated[dict[str, int], FieldX(RequestPart.PARAMS)]
    data: str = Field(alias="payload")


def test_request_factory_builds_request_parts():
    endpoint = Endpoint("GET", "/v1/items/{item_id}")

    def handler(
        self,
        item_id: str,
        payload: Payload,
        params: dict[str, int],
        headers: dict[str, str],
    ) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    arguments = endpoint.bind(
        client=client,
        args=("123", payload, {"limit": 5}, {"header": "h-1"}),
        kwargs={},
    )

    factory = RequestFactory(endpoint=endpoint)
    spec = factory(arguments)

    assert spec.path == "/v1/items/123"
    assert spec.parts["headers"] == {"token": "t-1", "header": "h-1"}
    assert spec.parts["params"] == {"q": 1, "limit": 5}
    assert spec.parts["json"] == {"data": "d-1"}


def test_request_factory_uses_section_annotation_on_parameter():
    endpoint = Endpoint("POST", "/v1/items")

    def handler(self, payload: Annotated[Payload, FieldX(RequestPart.JSON)]) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(payload,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["json"] == {"headers": {"token": "t-1"}, "params": {"q": 1}, "data": "d-1"}


def test_request_factory_applies_fieldx_dump_config():
    endpoint = Endpoint("POST", "/v1/items")

    class DataPayload(BaseModel):
        data: str
        optional: str | None = None

    def handler(
        self,
        payload: Annotated[
            DataPayload,
            FieldX(RequestPart.DATA, dump_config=DumpConfig(exclude_none=True)),
        ],
    ) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(DataPayload(data="d-1"),), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["data"] == {"data": "d-1"}


def test_merge_request_parts_warns_on_shared_dict_keys():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=True)

    with pytest.warns(UserWarning, match="share keys for 'headers'"):
        factory.merge_request_parts(
            [
                {"headers": {"token": "a"}},
                {"headers": {"token": "b", "other": "c"}},
            ]
        )


def test_merge_request_parts_warns_on_full_overwrite():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=True)

    with pytest.warns(UserWarning, match="fully overwritten"):
        factory.merge_request_parts(
            [
                {"json": {"a": 1}},
                {"json": "raw"},
            ]
        )


def test_merge_request_parts_silent_when_disabled():
    factory = RequestFactory(endpoint=Endpoint("GET", "/"), warn_on_conflict=False)

    factory.merge_request_parts(
        [
            {"headers": {"token": "a"}},
            {"headers": {"token": "b"}},
            {"json": {"a": 1}},
            {"json": "raw"},
        ]
    )


def test_argument_cursor_consumption_and_state():
    def handler(a: int, b: int = 2, c: int = 3): ...

    bound = inspect.signature(handler).bind(1)
    bound.apply_defaults()
    cursor = ArgumentCursor(bound)

    assert cursor.consume("a") == 1
    assert cursor.consume_optional("a", default=99) == 1
    assert cursor.consume_optional("missing", default=99) == 99
    assert cursor.is_consumed("a") is True
    assert cursor.is_consumed("b") is False
    assert cursor.consumed == {"a": 1}
    assert cursor.bound_copy == {"b": 2, "c": 3}


def test_argument_cursor_consume_errors():
    def handler(a: int): ...

    bound = inspect.signature(handler).bind(1)
    cursor = ArgumentCursor(bound)

    assert cursor.consume("a") == 1
    with pytest.raises(KeyError, match="already consumed"):
        cursor.consume("a")
    with pytest.raises(KeyError, match="not available"):
        cursor.consume("missing")


def test_model_extractor_groups_sections_and_defaults_json():
    class GroupedPayload(BaseModel):
        headers: Annotated[dict[str, str], FieldX(RequestPart.HEADERS)]
        params: Annotated[dict[str, int], FieldX(RequestPart.PARAMS)]
        data: str

    model = GroupedPayload(headers={"token": "t"}, params={"q": 1}, data="d")
    parts = ModelExtractor()(model, DumpConfig())

    assert parts[RequestPart.HEADERS] == {"token": "t"}
    assert parts[RequestPart.PARAMS] == {"q": 1}
    assert parts[RequestPart.JSON] == {"data": "d"}


def test_request_factory_raises_unconsumable_argument_error():
    endpoint = Endpoint("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, token: str) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("123", "t-1"), kwargs={})

    with pytest.raises(UnconsumableArgumentError, match="Cannot map argument 'token'"):
        RequestFactory(endpoint=endpoint)(arguments)


def test_request_factory_maps_scalar_param_using_fieldx_key():
    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[str, FieldX(RequestPart.PARAMS, key="type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=("block",), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "block"}


def test_request_factory_maps_enum_param_value_using_fieldx_key():
    class Kind(StrEnum):
        ALLOW = "allow"
        BLOCK = "block"

    endpoint = Endpoint("GET", "/v1/items")

    def handler(self, list_type: Annotated[Kind, FieldX(RequestPart.PARAMS, key="type")]) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    arguments = endpoint.bind(client=client, args=(Kind.ALLOW,), kwargs={})

    spec = RequestFactory(endpoint=endpoint)(arguments)

    assert spec.parts["params"] == {"type": "allow"}
