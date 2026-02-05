"""Response decoders for mapping HTTP responses into typed models."""

from dataclasses import dataclass, field
from typing import Protocol

from httpx import Response
from pydantic import BaseModel, TypeAdapter


@dataclass
class ModelDecoder[T: type[BaseModel]]:
    """Decode a response body into a Pydantic model instance."""

    model: T

    def __call__(self, response: Response) -> T:
        """Parse JSON content and validate it against the configured model.

        Args:
            response: HTTP response containing a JSON body.

        Returns:
            An instance of the configured Pydantic model.
        """
        data = response.json()

        return self.model.model_validate(data)


@dataclass
class TypeAdapterDecoder[T: TypeAdapter]:
    """Decode a response body using a Pydantic TypeAdapter."""

    adapter: T
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


class FromResponseModel[M: BaseModel](Protocol):
    """Protocol for models that construct themselves from HTTP responses."""

    @classmethod
    def from_response(cls, response: Response) -> M: ...


@dataclass
class FromResponseDecoder[T: BaseModel]:
    """Decode a response using a model's custom from-response constructor."""

    model: type[FromResponseModel[T]]

    def __call__(self, response: Response) -> T:
        """Return a model instance from the response object.

        Args:
            response: HTTP response used to build the model.

        Returns:
            An instance created by the model's ``from_response`` method.
        """
        return self.model.from_response(response)


__all__ = ["ModelDecoder", "TypeAdapterDecoder", "FromResponseDecoder"]
