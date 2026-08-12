from collections.abc import Callable
from typing import Any


class UnconsumableArgumentError(TypeError):
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
            "  • argument name is a RequestSection "
            "(e.g. 'json', 'params', 'data', 'files', 'headers')\n"
            "  • argument is Annotated[..., RequestSection.*]\n"
            "  • argument value is a pydantic BaseModel "
            "(expanded via ModelExtractor)\n"
            "Fix: rename the parameter, annotate it with RequestSection, "
            "or wrap it in a BaseModel."
        )

        super().__init__(message)


class UnprocessedArgumentsError(ValueError):
    """Raised when call arguments remain unprocessed."""

    def __init__(self, leftovers: dict[str, Any]) -> None:
        detail = ", ".join(f"{key}={value!r}" for key, value in leftovers.items())
        super().__init__(f"Unprocessed arguments: {detail}")
        self.leftovers = leftovers


class MissingPathArgumentsError(ValueError):
    """Raised when a path template is missing required arguments."""

    def __init__(self, path: str, missing_args: list[str]) -> None:
        """Store the path template and the missing argument names."""
        self.path = path
        self.missing_args = missing_args
        missing = ", ".join(missing_args)
        super().__init__(f"Missing path arguments for {repr(path)}: {missing}")


class MissingReturnTypeError(TypeError):
    """Raised when an endpoint function is missing a return annotation."""

    def __init__(self, func: Callable):
        qualname = getattr(func, "__qualname__", func.__name__)
        module = getattr(func, "__module__", "<unknown>")

        message = (
            f"Endpoint function '{qualname}' (defined in {module}) "
            "must declare a return type. "
            "QuickApiClient requires an explicit return annotation "
            "to determine response decoding behavior "
            "(e.g. `-> httpx2.Response`, `-> None`, or a typed value)."
        )

        super().__init__(message)


class MissingDecoderError(TypeError):
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
