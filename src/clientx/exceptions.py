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
            "  • argument name is a request part "
            "(e.g. 'json', 'params', 'data', 'files', 'headers')\n"
            "  • argument is annotated with a request part: "
            "Annotated[..., Query()], Header(), Form(), Body(), or File()\n"
            "  • argument value is a pydantic BaseModel\n"
            "Fix: rename the parameter, annotate it with Query(...), Header(...), Form(...), Body() or File(), "
            "or wrap it in a BaseModel."
        )

        super().__init__(message)


class MissingPathArgumentsError(ClientXError, ValueError):
    """Raised when a path template has placeholders that no argument fills.

    An endpoint raises it when its class is defined, if a placeholder in its path
    (including one from a ``Resource`` prefix) doesn't name one of its parameters.
    """

    def __init__(self, path: str, missing_args: list[str], *, func: Callable[..., Any] | None = None) -> None:
        """Store the path template, the missing argument names, and the endpoint function if known."""
        self.path = path
        self.missing_args = missing_args
        missing = ", ".join(missing_args)
        if func is None:
            super().__init__(f"Missing path arguments for {repr(path)}: {missing}")
            return
        qualname = getattr(func, "__qualname__", func.__name__)
        module = getattr(func, "__module__", "<unknown>")
        super().__init__(
            f"Missing path arguments for {repr(path)}: {missing}. "
            f"Endpoint function '{qualname}' (defined in {module}) needs a parameter "
            "for each placeholder in its path."
        )


class EndpointSignatureError(ClientXError, TypeError):
    """Raised when the class is defined, if an endpoint's parameters can't describe a request.

    The first parameter receives the client or resource (it's usually named ``self``),
    so it must be positional. Every other parameter must be named: ``*args`` and
    ``**kwargs`` have no place in a request.
    """

    def __init__(self, func: Callable[..., Any], problem: str) -> None:
        """Store the endpoint function and describe the problem."""
        self.func = func
        qualname = getattr(func, "__qualname__", func.__name__)
        module = getattr(func, "__module__", "<unknown>")
        super().__init__(f"Endpoint function '{qualname}' (defined in {module}) {problem}.")


class MissingReturnTypeError(ClientXError, TypeError):
    """Raised when an endpoint function is missing a return annotation."""

    def __init__(self, func: Callable[..., Any]):
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

    def __init__(self, func: Callable[..., Any]):
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


class EndpointNameConflictError(ClientXError, TypeError):
    """Raised when an endpoint or mounted resource uses a name that its base class already uses.

    Endpoints and resources on a ``ClientX`` subclass can't reuse names that
    ``ClientX`` defines (such as ``user_agent`` or ``client``); on a ``Resource``
    subclass, only the names ``Resource`` itself defines are reserved.
    """

    def __init__(self, *, owner: type, name: str, base: str) -> None:
        message = (
            f"'{owner.__qualname__}.{name}' (defined in {owner.__module__}) "
            f"can't be named '{name}': {base} already uses that name, "
            "and overriding it breaks the client. Rename it."
        )

        super().__init__(message)


class UnboundResourceError(ClientXError, TypeError):
    """Raised when an endpoint is called on a resource that isn't mounted on a client."""

    def __init__(self, resource: type) -> None:
        name = resource.__qualname__
        message = (
            f"Resource '{name}' isn't mounted on a client. Mount an instance as a class "
            f"attribute of a ClientX subclass (for example, `items = {name}()`) and call "
            "its endpoints through a client instance (`client.items.<endpoint>(...)`)."
        )

        super().__init__(message)


class MisplacedHelperError(ClientXError, TypeError):
    """Raised when a request-part helper isn't the one helper in the outermost ``Annotated``.

    A helper (``Query``, ``Header``, ``Form``, ``Body`` or ``File``) applies to a whole
    parameter or model field, so it goes around the full type, ``None`` included:
    ``Annotated[int | None, Query()]``. A helper nested inside another type, such as
    ``Annotated[int, Query()] | None``, or a second helper, would be ignored.
    """

    def __init__(self, name: str, annotation: Any, problem: str) -> None:
        self.name = name
        self.annotation = annotation
        message = (
            f"{problem}.\n"
            "A helper applies to the whole parameter or field: use one helper, in the outermost Annotated, "
            "around the full type with None included, such as Annotated[int | None, Query()] rather than "
            "Annotated[int, Query()] | None. If the request part depends on the value's type, use separate "
            "endpoints."
        )

        super().__init__(message)


__all__ = [
    "ClientXError",
    "EndpointNameConflictError",
    "EndpointSignatureError",
    "MisplacedHelperError",
    "MissingDecoderError",
    "MissingPathArgumentsError",
    "MissingReturnTypeError",
    "UnboundResourceError",
    "UnconsumableArgumentError",
]
