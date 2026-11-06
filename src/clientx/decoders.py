"""Response decoders for mapping HTTP responses into typed models."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from httpx2 import Response
from pydantic import BaseModel, TypeAdapter


# vanilla httpx2 response decoders
def json_decoder(response: Response) -> Any:
    return response.json()


def content_decoder(response: Response) -> bytes:
    return response.content


def text_decoder(response: Response) -> str:
    return response.text


class StreamDecoder[T](ABC):
    """Base decoder for streamed HTTP responses.

    Subclasses should yield data incrementally and must not materialize the
    full response payload in memory.

    Attributes:
        stream: Read by the endpoint decorators. When an endpoint does not pass
            ``stream=`` explicitly, a decoder with a truthy ``stream`` attribute
            makes the request use streaming mode, so the body is not buffered
            before decoding. Custom decoders can opt in by defining it too.
    """

    stream: bool = True

    @abstractmethod
    def __call__(self, response: Response) -> Iterator[T]:
        """Yield decoded stream items from the response body.

        Args:
            response: HTTP response containing a streamed body.
        """
        ...


@dataclass
class StreamLinesDecoder(StreamDecoder[str]):
    """Yield streamed response text line-by-line."""

    def __call__(self, response: Response) -> Iterator[str]:
        yield from response.iter_lines()


@dataclass
class StreamChunksDecoder(StreamDecoder[bytes]):
    """Yield streamed response body as raw byte chunks."""

    chunk_size: int | None = field(default=None, kw_only=True)

    def __call__(self, response: Response) -> Iterator[bytes]:
        yield from response.iter_bytes(chunk_size=self.chunk_size)


# Pydantic base model decoders
@dataclass
class ModelDecoder[M: BaseModel]:
    """Decode a response body into a Pydantic model instance."""

    model: type[M]

    def __call__(self, response: Response) -> M:
        """Parse JSON content and validate it against the configured model.

        Args:
            response: HTTP response containing a JSON body.

        Returns:
            An instance of the configured Pydantic model.
        """
        data = response.json()

        return self.model.model_validate(data)


@dataclass
class TypeAdapterDecoder[T]:
    """Decode a response body using a Pydantic TypeAdapter."""

    adapter: TypeAdapter[T]
    key: str | None = field(default=None, kw_only=True)

    def __call__(self, response: Response) -> T:
        """Parse JSON content and validate it with the configured adapter.

        Args:
            response: HTTP response containing a JSON body.

        Returns:
            The validated Python object produced by the adapter.
        """
        data = response.json()
        data = data[self.key] if self.key else data
        return self.adapter.validate_python(data)


class _FromResponseModel[M: BaseModel](Protocol):
    """Protocol for models that construct themselves from HTTP responses."""

    @classmethod
    def from_response(cls, response: Response) -> M: ...


@dataclass
class FromResponseDecoder[T: BaseModel]:
    """Decode a response using a model's custom from_response constructor."""

    model: type[_FromResponseModel[T]]

    def __call__(self, response: Response) -> T:
        """Return a model instance from the response object.

        Args:
            response: HTTP response used to build the model.

        Returns:
            An instance created by the model's ``from_response`` method.
        """
        return self.model.from_response(response)


__all__ = [
    "FromResponseDecoder",
    "ModelDecoder",
    "StreamChunksDecoder",
    "StreamDecoder",
    "StreamLinesDecoder",
    "TypeAdapterDecoder",
    "content_decoder",
    "json_decoder",
    "text_decoder",
]
