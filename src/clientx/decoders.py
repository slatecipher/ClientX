"""Response decoders for mapping HTTP responses into typed models."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

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

    Endpoints that use a ``StreamDecoder`` send their request in streaming mode,
    so the body is not loaded into memory first. ClientX closes the response when
    iteration over the decoder's output finishes, stops early, or fails.

    Subclasses should yield data incrementally and must not materialize the
    full response payload in memory.
    """

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


@dataclass(frozen=True)
class StreamResponseDecoder:
    """Return the open streamed response itself, for endpoints annotated ``-> Response``.

    The request is sent in streaming mode and the caller owns the response: read
    it, iterate it to the end, or call ``response.close()`` to release the
    connection.
    """

    def __call__(self, response: Response) -> Response:
        return response


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
    """Decode a JSON response body with a Pydantic ``TypeAdapter``, for types that aren't models.

    Use it for lists, unions, and other types: ``TypeAdapterDecoder(TypeAdapter(list[User]))``
    for an endpoint annotated ``-> list[User]``. With ``key``, it validates one member of a
    JSON object instead of the whole body, for APIs that wrap their data in an object::

        @get("/users", decoder=TypeAdapterDecoder(TypeAdapter(list[User]), key="results"))
        def list_users(self) -> list[User]: ...  # {"count": 2, "results": [...]} -> list[User]

    Attributes:
        adapter: The ``TypeAdapter`` that validates the data. It takes a ``TypeAdapter``,
            not a bare type.
        key: The member of the JSON object to validate instead of the whole body, or
            ``None`` to validate the whole body.
    """

    adapter: TypeAdapter[T]
    key: str | None = field(default=None, kw_only=True)

    def __call__(self, response: Response) -> T:
        """Parse the JSON body and validate it, or its ``key`` member, with the adapter.

        Args:
            response: HTTP response with a JSON body.

        Returns:
            The validated value.

        Raises:
            json.JSONDecodeError: If the body isn't JSON. It's a ``ValueError``.
            ValueError: If ``key`` is set and the body isn't a JSON object with that key.
            pydantic.ValidationError: If the data doesn't match the adapter's type. It's a
                ``ValueError`` too.
        """
        data = response.json()
        if self.key is not None:
            data = _member(data, self.key)
        return self.adapter.validate_python(data)


def _member(data: object, key: str) -> object:
    """Return ``data[key]``, or raise ``ValueError`` if ``data`` isn't a JSON object with that key."""
    members = _json_object(data)
    if members is None or key not in members:
        raise ValueError(
            f"TypeAdapterDecoder(key={key!r}) expected a JSON object with a {key!r} key, "
            f"but the response body is {_describe_json(data)}."
        )
    return members[key]


def _json_object(data: object) -> dict[str, object] | None:
    """Return ``data`` if it's a decoded JSON object, else ``None``."""
    return cast("dict[str, object]", data) if isinstance(data, dict) else None


# How a decoded JSON value is described in error messages, by its Python type.
_JSON_TYPES: dict[type[object], str] = {
    list: "an array",
    str: "a string",
    int: "a number",
    float: "a number",
    bool: "a boolean",
}


def _describe_json(data: object) -> str:
    """Describe a decoded JSON value by its JSON type, naming an object's first keys."""
    members = _json_object(data)
    if members is None:
        return "null" if data is None else _JSON_TYPES.get(type(data), type(data).__name__)
    if not members:
        return "an empty object"
    shown = ", ".join(repr(name) for name in list(members)[:5])
    more = f" and {len(members) - 5} more" if len(members) > 5 else ""
    return f"an object with the keys {shown}{more}"


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
    "StreamResponseDecoder",
    "TypeAdapterDecoder",
    "content_decoder",
    "json_decoder",
    "text_decoder",
]
