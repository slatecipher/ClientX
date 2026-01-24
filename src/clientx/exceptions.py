from typing import Callable


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
            "(e.g. `-> httpx.Response`, `-> None`, or a typed value)."
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
            "`httpx.Response` or `None`. "
            "Provide a decoder callable via the endpoint decorator "
            "or change the return type to `httpx.Response` or `None`."
        )

        super().__init__(message)
