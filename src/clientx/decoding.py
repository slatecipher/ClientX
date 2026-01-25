from dataclasses import dataclass, field
from typing import Protocol, Type

from httpx import Response
from pydantic import BaseModel, TypeAdapter


@dataclass
class ModelDecoder[T: Type[BaseModel]]:
    model: T

    def __call__(self, response: Response) -> T:
        data = response.json()

        return self.model.model_validate(data)


@dataclass
class TypeAdapterDecoder[T: TypeAdapter]:
    adapter: T
    key: str | None = field(default=None, kw_only=True)

    def __call__(self, response: Response) -> T:
        data = response.json()
        data = data[self.key] if self.key else data
        return self.adapter.validate_python(data)


__all__ = ["ModelDecoder", "TypeAdapterDecoder"]
