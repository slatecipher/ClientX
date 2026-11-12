"""Decoders: turn an endpoint's response into the value its method returns.

Pass one as an endpoint's ``decoder=``. Its return type must match the method's
annotation, and type checkers check that. Any callable that takes an
``httpx2.Response`` works as a decoder; these cover the common cases:

- ``ModelDecoder`` and ``TypeAdapterDecoder`` validate a JSON body with Pydantic.
- ``FromResponseDecoder`` builds a model with the model's own ``from_response`` classmethod.
- ``json_decoder``, ``text_decoder``, and ``content_decoder`` return the body without validating it.
- ``StreamLinesDecoder``, ``StreamChunksDecoder``, and other ``StreamDecoder`` subclasses
  stream the body. ``StreamResponseDecoder`` returns the open streamed response.

A 4xx or 5xx response raises ``httpx2.HTTPStatusError`` before the decoder runs. An
exception a decoder raises reaches the caller unchanged.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from httpx2 import Response
from pydantic import BaseModel, TypeAdapter


# vanilla httpx2 response decoders
def json_decoder(response: Response) -> Any:
    """Return the parsed JSON body, without validating it.

    The result is ``Any``, so type checkers accept it for any return annotation. For a
    checked result, use ``ModelDecoder`` or ``TypeAdapterDecoder``.

    Raises:
        json.JSONDecodeError: If the body isn't JSON. It's a ``ValueError``.
    """
    return response.json()


def content_decoder(response: Response) -> bytes:
    """Return the body as bytes, for an endpoint annotated ``-> bytes``."""
    return response.content


def text_decoder(response: Response) -> str:
    """Return the body as text, for an endpoint annotated ``-> str``.

    The text is decoded with the response's encoding: the charset in its
    ``Content-Type`` header, or else the client's ``default_encoding``.
    """
    return response.text


class StreamDecoder[T](ABC):
    """Base class for decoders that stream the response body.

    An endpoint with a ``StreamDecoder`` sends its request in streaming mode, so the
    body isn't read into memory first, and returns the decoder's iterator: annotate
    it ``-> Iterator[T]``. ClientX closes the response when iteration finishes, stops
    early, or fails.

    A subclass yields items as the body arrives, and must not read the whole body
    first. For example, a decoder for JSON Lines::

        class JSONLinesDecoder(StreamDecoder[dict[str, Any]]):
            def __call__(self, response: Response) -> Iterator[dict[str, Any]]:
                for line in response.iter_lines():
                    if line:
                        yield json.loads(line)
    """

    @abstractmethod
    def __call__(self, response: Response) -> Iterator[T]:
        """Yield items decoded from the streamed body.

        Args:
            response: The open, streamed HTTP response.

        Yields:
            Decoded items, as the body arrives.
        """
        ...


@dataclass
class StreamLinesDecoder(StreamDecoder[str]):
    """Yield the streamed body as lines of text, for an endpoint annotated ``-> Iterator[str]``.

    Lines end at ``\\n``, ``\\r\\n``, or ``\\r``, and are yielded without their line
    endings; a blank line is yielded as ``""``. The text is decoded with the response's
    encoding, as for ``text_decoder``.
    """

    def __call__(self, response: Response) -> Iterator[str]:
        yield from response.iter_lines()


@dataclass
class StreamChunksDecoder(StreamDecoder[bytes]):
    """Yield the streamed body as chunks of bytes, for an endpoint annotated ``-> Iterator[bytes]``.

    The body is decompressed as its ``Content-Encoding`` says, such as ``gzip``.

    Attributes:
        chunk_size: The size of each chunk in bytes (the last one can be smaller), or
            ``None`` to yield chunks as they arrive from the network.
    """

    chunk_size: int | None = field(default=None, kw_only=True)

    def __call__(self, response: Response) -> Iterator[bytes]:
        yield from response.iter_bytes(chunk_size=self.chunk_size)


@dataclass(frozen=True)
class StreamResponseDecoder:
    """Return the open streamed response itself, for endpoints annotated ``-> Response``.

    The request is sent in streaming mode and the caller owns the response: read
    it, iterate it to the end, or call ``response.close()`` to release the
    connection. Use it to hand the body to code that reads it itself, such as
    writing a download to a file with ``response.iter_bytes()``.
    """

    def __call__(self, response: Response) -> Response:
        return response


# Pydantic base model decoders
@dataclass
class ModelDecoder[M: BaseModel]:
    """Decode a JSON response body into a Pydantic model: ``decoder=ModelDecoder(User)`` for ``-> User``.

    Attributes:
        model: The model class that validates the body, with its own configuration, so
            aliases and validators apply.
    """

    model: type[M]

    def __call__(self, response: Response) -> M:
        """Parse the JSON body and validate it with the model.

        Args:
            response: HTTP response with a JSON body.

        Returns:
            An instance of the model.

        Raises:
            json.JSONDecodeError: If the body isn't JSON. It's a ``ValueError``.
            pydantic.ValidationError: If the body doesn't match the model. It's a
                ``ValueError`` too.
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
    """Decode a response with a model's own ``from_response`` classmethod.

    Use it when the value needs more than the JSON body, such as headers or the
    status code. The model defines the classmethod, and
    ``decoder=FromResponseDecoder(Session)`` pairs with ``-> Session``::

        class Session(BaseModel):
            token: str
            status_code: int

            @classmethod
            def from_response(cls, response: Response) -> "Session":
                return cls(token=response.headers["X-Session-Token"], status_code=response.status_code)

    Attributes:
        model: The model class whose ``from_response`` builds the value.
    """

    model: type[_FromResponseModel[T]]

    def __call__(self, response: Response) -> T:
        """Build the value with the model's ``from_response``.

        Args:
            response: The HTTP response.

        Returns:
            The model instance ``from_response`` returns. Any exception it raises
            reaches the caller unchanged.
        """
        return self.model.from_response(response)


__all__ = [
    "FromResponseDecoder",
    "ModelDecoder",
    "StreamChunksDecoder",
    "StreamDecoder",
    "StreamLinesDecoder",
    "StreamResponseDecoder",
    "TypeAdapterDecoder",
    "content_decoder",
    "json_decoder",
    "text_decoder",
]
