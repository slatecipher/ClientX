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
    """Raised when an argument, or a field of a model argument, cannot be mapped into an HTTP request part.

    An argument can't be mapped when nothing chooses a request part for it. A model
    field marked ``Body()`` or ``File()`` can't be mapped when its value isn't a
    mapping or a model, because the value is merged into that part.
    """

    def __init__(self, *, field: str, annotation: Any, value: Any, problem: str | None = None) -> None:
        """Store the argument or field, its annotation, and its value, and describe the problem.

        Args:
            field: The parameter name, or ``Model.field`` for a model field.
            annotation: The parameter's or field's annotation.
            value: The value that couldn't be mapped.
            problem: What's wrong and how to fix it. Without it, the message lists
                the ways an argument can be mapped to a request part.
        """
        self.field = field
        self.annotation = annotation
        self.value = value

        value_type = type(value).__name__
        details = f"  value_type: {value_type}\n  annotation: {annotation!r}\n"

        if problem is not None:
            super().__init__(f"Cannot map {field!r} into an HTTP request part.\n{details}{problem}")
            return

        message = (
            f"Cannot map argument '{field}' into an HTTP request part.\n"
            f"{details}"
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
    ``ClientX`` defines (such as ``close`` or ``__enter__``); on a ``Resource``
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


class PathTemplateError(ClientXError, ValueError):
    """Raised when the class is defined, if an endpoint's path template is invalid.

    A placeholder is ``{name}``, or ``{name:path}`` to keep slashes in the value.
    Any other converter, such as ``{user_id:int}``, raises this error.
    """

    def __init__(self, path: str, problem: str) -> None:
        """Store the path template and describe the problem."""
        self.path = path
        super().__init__(
            f"Invalid path template {path!r}: {problem}. "
            "Use {name} for one path segment, or {name:path} to keep slashes in the value."
        )


class PathValueError(ClientXError, ValueError):
    """Raised before a request is sent, if a path value would change which path is called.

    A value fills one ``{placeholder}``, so it must render to at least one character:
    ``None`` would be sent as ``null``, and an empty string would call a different path
    (``/users/{user_id}`` with ``""`` would call ``/users/``). For a ``{name:path}``
    placeholder, each segment between slashes must be non-empty too, so a leading,
    trailing, or doubled slash raises this error.

    Attributes:
        path: The endpoint's path template.
        parameter: The name of the placeholder the value was for.
        value: The value that was passed.
    """

    def __init__(self, path: str, parameter: str, value: object, problem: str) -> None:
        """Store the path template, the placeholder, and the value, and describe the problem."""
        self.path = path
        self.parameter = parameter
        self.value = value
        super().__init__(f"Can't fill {{{parameter}}} in {path!r} with {value!r}: {problem}. No request was sent.")


class ArgumentValidationError(ClientXError, ValueError):
    """Raised before a request is sent, if an argument doesn't match its parameter's annotation.

    Only raised when argument validation is on: ``ClientX(..., validate_arguments=True)``,
    or ``validate_arguments=True`` on the endpoint's decorator. The check is strict, like
    a type checker's: ``"1"`` doesn't match ``int``. ``Field`` constraints such as
    ``ge=1`` apply too. The value is never changed.

    Attributes:
        func: The endpoint function.
        parameter: The parameter whose argument didn't match.
        validation_error: Pydantic's error, with the details.
    """

    def __init__(self, func: Callable[..., Any], parameter: str, validation_error: Exception) -> None:
        """Store the endpoint function, the parameter, and Pydantic's error."""
        self.func = func
        self.parameter = parameter
        self.validation_error = validation_error
        qualname = getattr(func, "__qualname__", func.__name__)
        super().__init__(
            f"Argument {parameter!r} of '{qualname}' doesn't match its annotation, so no request was sent.\n"
            f"{validation_error}"
        )


__all__ = [
    "ArgumentValidationError",
    "ClientXError",
    "EndpointNameConflictError",
    "EndpointSignatureError",
    "MisplacedHelperError",
    "MissingDecoderError",
    "MissingPathArgumentsError",
    "MissingReturnTypeError",
    "PathTemplateError",
    "PathValueError",
    "UnboundResourceError",
    "UnconsumableArgumentError",
]
