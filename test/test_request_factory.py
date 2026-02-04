import inspect
from typing import Annotated, cast

import pytest
from pydantic import BaseModel, Field

from clientx.annotations import DumpOptions, RequestSection
from clientx.call_context import CallContext
from clientx.client import ClientX
from clientx.endpoint_context import EndpointContext
from clientx.exceptions import UnconsumableArgumentError
from clientx.request_factory import ArgumentCursor, ModelExtractor, RequestFactory


class Payload(BaseModel):
    headers: Annotated[dict[str, str], RequestSection.HEADERS]
    params: Annotated[dict[str, int], RequestSection.PARAMS]
    data: str = Field(alias="payload")


def test_request_factory_builds_request_parts():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

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
    call_ctx = CallContext.from_call(
        endpoint=endpoint,
        client=client,
        args=("123", payload, {"limit": 5}, {"header": "h-1"}),
        kwargs={},
    )

    factory = RequestFactory()
    request = factory(call_ctx)

    assert request["path"] == "/v1/items/123"
    assert request["headers"] == {"token": "t-1", "header": "h-1"}
    assert request["params"] == {"q": 1, "limit": 5}
    assert request["json"] == {"data": "d-1"}


def test_request_factory_uses_section_annotation_on_parameter():
    endpoint = EndpointContext("POST", "/v1/items")

    def handler(self, payload: Annotated[Payload, RequestSection.JSON]) -> None: ...

    endpoint.func = handler

    payload = Payload(headers={"token": "t-1"}, params={"q": 1}, payload="d-1")
    client = cast(ClientX, object())
    call_ctx = CallContext.from_call(
        endpoint=endpoint,
        client=client,
        args=(payload,),
        kwargs={},
    )

    request = RequestFactory()(call_ctx)

    assert request["json"] == {"headers": {"token": "t-1"}, "params": {"q": 1}, "data": "d-1"}


def test_merge_request_parts_warns_on_shared_dict_keys():
    factory = RequestFactory(warn_on_conflict=True)

    with pytest.warns(UserWarning, match="share keys for 'headers'"):
        factory.merge_request_parts(
            [
                {"headers": {"token": "a"}},
                {"headers": {"token": "b", "other": "c"}},
            ]
        )


def test_merge_request_parts_warns_on_full_overwrite():
    factory = RequestFactory(warn_on_conflict=True)

    with pytest.warns(UserWarning, match="fully overwritten"):
        factory.merge_request_parts(
            [
                {"json": {"a": 1}},
                {"json": "raw"},
            ]
        )


def test_merge_request_parts_silent_when_disabled():
    factory = RequestFactory(warn_on_conflict=False)

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
    assert cursor.leftovers() == {"b": 2, "c": 3}
    assert cursor.consumed_items() == {"a": 1}

    with pytest.raises(TypeError, match="Unhandled arguments"):
        cursor.assert_empty()


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
        headers: Annotated[dict[str, str], RequestSection.HEADERS]
        params: Annotated[dict[str, int], RequestSection.PARAMS]
        data: str

    model = GroupedPayload(headers={"token": "t"}, params={"q": 1}, data="d")
    parts = ModelExtractor()(model, DumpOptions())

    assert parts[RequestSection.HEADERS] == {"token": "t"}
    assert parts[RequestSection.PARAMS] == {"q": 1}
    assert parts[RequestSection.JSON] == {"data": "d"}


def test_request_factory_raises_unconsumable_argument_error():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

    def handler(self, item_id: str, token: str) -> None: ...

    endpoint.func = handler

    client = cast(ClientX, object())
    call_ctx = CallContext.from_call(
        endpoint=endpoint,
        client=client,
        args=("123", "t-1"),
        kwargs={},
    )

    with pytest.raises(UnconsumableArgumentError, match="Cannot map argument 'token'"):
        RequestFactory()(call_ctx)
