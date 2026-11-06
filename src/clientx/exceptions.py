"""Exceptions raised by ClientX.

Every exception derives from ``ClientXError``, so ``except ClientXError`` catches
them all. Each one also keeps a built-in base (``TypeError`` or ``ValueError``),
so existing ``except TypeError`` / ``except ValueError`` handlers keep working.
"""

from collections.abc import Callable
from typing import Any


class ClientXError(Exception):
    """Base class for all ClientX exceptions."""


class UnconsumableArgumentError(ClientXError, TypeError):
    """Raised when an argument cannot be mapped into an HTTP request part."""

    def __init__(self, *, field: str, annotation: Any, value: Any) -> None:
        self.field = field
        self.annotation = annotation
        self.value = value

        value_type = type(value).__name__

        message = (
            f"Cannot map argument '{field}' into an HTTP request part.\n"
            f"  value_type: {value_type}\n"
            f"  annotation: {annotation!r}\n"
            "Expected one of:\n"
            "  • argument name is a RequestPart "
            "(e.g. 'json', 'params', 'data', 'files', 'headers')\n"
            "  • argument is Annotated[..., FieldX(RequestPart.*)]\n"
            "  • argument value is a pydantic BaseModel\n"
            "Fix: rename the parameter, annotate it with FieldX(RequestPart.*), "
            "or wrap it in a BaseModel."
        )

        super().__init__(message)


class MissingPathArgumentsError(ClientXError, ValueError):
    """Raised when a path template is missing required arguments."""

    def __init__(self, path: str, missing_args: list[str]) -> None:
        """Store the path template and the missing argument names."""
        self.path = path
        self.missing_args = missing_args
        missing = ", ".join(missing_args)
        super().__init__(f"Missing path arguments for {repr(path)}: {missing}")


class MissingReturnTypeError(ClientXError, TypeError):
    """Raised when an endpoint function is missing a return annotation."""

    def __init__(self, func: Callable):
        qualname = getattr(func, "__qualname__", func.__name__)
        module = getattr(func, "__module__", "<unknown>")

        message = (
            f"Endpoint function '{qualname}' (defined in {module}) "
            "must declare a return type. "
            "ClientX requires an explicit return annotation "
            "to determine response decoding behavior "
            "(e.g. `-> httpx2.Response`, `-> None`, or a typed value)."
        )

        super().__init__(message)


class MissingDecoderError(ClientXError, TypeError):
    """Raised when a decoder is required but not provided."""

    def __init__(self, func: Callable):
        qualname = getattr(func, "__qualname__", func.__name__)
        module = getattr(func, "__module__", "<unknown>")

        message = (
            f"Endpoint function '{qualname}' (defined in {module}) "
            "requires a decoder because its return type is not "
            "`httpx2.Response` or `None`. "
            "Provide a decoder callable via the endpoint decorator "
            "or change the return type to `httpx2.Response` or `None`."
        )

        super().__init__(message)


__all__ = [
    "ClientXError",
    "MissingDecoderError",
    "MissingPathArgumentsError",
    "MissingReturnTypeError",
    "UnconsumableArgumentError",
]
