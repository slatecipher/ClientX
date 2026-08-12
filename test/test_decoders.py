from collections.abc import Iterator

from httpx2 import Response
from pydantic import BaseModel, TypeAdapter

from clientx.decoders import (
    FromResponseDecoder,
    ModelDecoder,
    StreamChunksDecoder,
    StreamDecoder,
    StreamLinesDecoder,
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


def test_stream_decoders_opt_into_stream_mode():
    assert StreamLinesDecoder().stream is True
    assert StreamChunksDecoder().stream is True
    assert isinstance(StreamLinesDecoder(), StreamDecoder)


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
