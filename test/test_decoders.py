from collections.abc import Callable, Iterator

import pytest
from httpx2 import Response
from pydantic import BaseModel, TypeAdapter

from clientx.decoders import (
    FromResponseDecoder,
    ModelDecoder,
    StreamChunksDecoder,
    StreamDecoder,
    StreamLinesDecoder,
    StreamResponseDecoder,
    TypeAdapterDecoder,
    content_decoder,
    json_decoder,
    text_decoder,
)


def test_json_decoder_returns_response_json():
    response = Response(200, json={"ok": True, "count": 2})

    assert json_decoder(response) == {"ok": True, "count": 2}


def test_content_decoder_returns_response_content():
    response = Response(200, content=b"abc123")

    assert content_decoder(response) == b"abc123"


def test_text_decoder_returns_response_text():
    response = Response(200, content=b"hello")

    assert text_decoder(response) == "hello"


def test_stream_lines_decoder_yields_lines():
    response = Response(200, content=b"alpha\nbeta\n")

    result = StreamLinesDecoder()(response)

    assert isinstance(result, Iterator)
    assert list(result) == ["alpha", "beta"]


def test_stream_chunks_decoder_yields_chunks():
    response = Response(200, content=b"alpha")

    result = StreamChunksDecoder(chunk_size=2)(response)

    assert isinstance(result, Iterator)
    assert list(result) == [b"al", b"ph", b"a"]


def test_builtin_stream_decoders_are_stream_decoders():
    assert isinstance(StreamLinesDecoder(), StreamDecoder)
    assert isinstance(StreamChunksDecoder(), StreamDecoder)


def test_stream_response_decoder_returns_the_response_itself():
    response = Response(200, content=b"payload")

    assert StreamResponseDecoder()(response) is response


def test_model_decoder_validates_with_model():
    class Item(BaseModel):
        id: int
        name: str

    response = Response(200, json={"id": 1, "name": "widget"})

    result = ModelDecoder(Item)(response)

    assert isinstance(result, Item)
    assert result.id == 1
    assert result.name == "widget"


def test_type_adapter_decoder_validates_entire_payload():
    response = Response(200, json=[1, 2, 3])

    result = TypeAdapterDecoder(TypeAdapter(list[int]))(response)

    assert result == [1, 2, 3]


def test_type_adapter_decoder_validates_payload_by_key():
    response = Response(200, json={"sessions": [{"id": 1}, {"id": 2}]})

    result = TypeAdapterDecoder(TypeAdapter(list[dict[str, int]]), key="sessions")(response)

    assert result == [{"id": 1}, {"id": 2}]


@pytest.mark.parametrize(
    ("content", "body"),
    [
        (b'{"count": 2, "items": []}', "an object with the keys 'count', 'items'"),
        (
            b'{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7}',
            "an object with the keys 'a', 'b', 'c', 'd', 'e' and 2 more",
        ),
        (b"{}", "an empty object"),
        (b"[1, 2]", "an array"),
        (b'"text"', "a string"),
        (b"3", "a number"),
        (b"true", "a boolean"),
        (b"null", "null"),
    ],
    ids=["other keys", "many keys", "empty object", "array", "string", "number", "boolean", "null"],
)
def test_type_adapter_decoder_says_when_the_key_is_missing(content: bytes, body: str):
    decoder = TypeAdapterDecoder(TypeAdapter(list[int]), key="results")

    with pytest.raises(ValueError) as raised:
        decoder(Response(200, content=content))

    assert str(raised.value) == (
        "TypeAdapterDecoder(key='results') expected a JSON object with a 'results' key, "
        f"but the response body is {body}."
    )


class Item(BaseModel):
    id: int


@pytest.mark.parametrize(
    ("decoder", "content"),
    [
        (ModelDecoder(Item), b"<html>"),
        (ModelDecoder(Item), b'{"id": "x"}'),
        (TypeAdapterDecoder(TypeAdapter(list[Item]), key="items"), b"[]"),
    ],
    ids=["not JSON", "doesn't validate", "missing key"],
)
def test_built_in_decoder_failures_are_value_errors(decoder: Callable[[Response], object], content: bytes):
    # The README promises `except ValueError` catches them all.
    with pytest.raises(ValueError):
        decoder(Response(200, content=content))


def test_from_response_decoder_uses_model_constructor():
    class SessionPayload(BaseModel):
        token: str
        status_code: int

        @classmethod
        def from_response(cls, response: Response) -> "SessionPayload":
            payload = response.json()
            return cls(token=payload["token"], status_code=response.status_code)

    response = Response(201, json={"token": "abc"})

    result = FromResponseDecoder(SessionPayload)(response)

    assert isinstance(result, SessionPayload)
    assert result.token == "abc"
    assert result.status_code == 201
