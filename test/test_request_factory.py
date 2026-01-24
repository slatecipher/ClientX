import inspect
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, computed_field

from clientx.call_context import CallContext
from clientx.endpoint_context import EndpointContext
from clientx.request_factory import (
    ArgumentCursor,
    FieldRequestParts,
    ModelRequestParts,
    RequestFactory,
    ReqPart,
)


class Payload(BaseModel):
    token: Annotated[str, ReqPart.HEADERS]
    q: Annotated[str, ReqPart.PARAMS]
    data: Annotated[str, ReqPart.JSON] = Field(alias="payload")


def test_request_factory_builds_request_parts():
    endpoint = EndpointContext("GET", "/v1/items/{item_id}")

    def handler(
        self,
        item_id: str,
        payload: Payload,
        limit: Annotated[int, ReqPart.PARAMS],
        header: Annotated[str, ReqPart.HEADERS],
    ) -> None: ...

    endpoint.func = handler

    payload = Payload(token="t-1", q="q-1", payload="d-1")
    client = object()
    call_ctx = CallContext.from_call(
        endpoint=endpoint,
        client=client,
        args=("123", payload, 5, "h-1"),
        kwargs={},
    )

    factory = RequestFactory()
    request = factory(call_ctx)

    assert request["path"] == "/v1/items/123"
    assert request["headers"] == {"token": "t-1", "header": "h-1"}
    assert request["params"] == {"q": "q-1", "limit": 5}
    assert request["json"] == {"data": "d-1"}


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


def test_field_request_parts_returns_none_without_request_field():
    cursor = ArgumentCursor(inspect.signature(lambda a: None).bind(1))
    field_parts = FieldRequestParts()

    assert field_parts("a", Annotated[int, "meta"], cursor) is None


def test_model_request_parts_field_matches_request_part():
    model_parts = ModelRequestParts()
    dump = {"json": {"a": 1}}
    part_map = {ReqPart.JSON: {("json", None)}}

    parts = model_parts.build_request_parts(dump, part_map)

    assert parts["json"] == {"a": 1}


def test_model_request_parts_explicit_request_keys():
    model_parts = ModelRequestParts()
    dump = {"json": {"a": 1}, "files": {"f": "x"}}

    parts = model_parts.build_request_parts(dump, {})

    assert parts[ReqPart.JSON] == {"a": 1}
    assert parts[ReqPart.FILES] == {"f": "x"}


def test_model_request_parts_defaults_remaining_to_json():
    class RemainingPayload(BaseModel):
        extra: str

    model = RemainingPayload(extra="e")
    parts = ModelRequestParts()(model)

    assert parts["json"] == {"extra": "e"}


def test_get_request_field_map_includes_computed_fields():
    class ComputedPayload(BaseModel):
        token: str

        @computed_field
        @property
        def auth(self) -> Annotated[str, ReqPart.HEADERS]:
            return self.token

    mapping = ModelRequestParts().get_request_field_map(ComputedPayload(token="t"))

    assert mapping == {ReqPart.HEADERS: {("auth", None)}}
