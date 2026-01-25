from __future__ import annotations

import inspect
import re
import warnings
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Type, get_type_hints

from clientx.client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.exceptions import MissingDecoderError, MissingPathArgumentsError, MissingReturnTypeError


@dataclass(frozen=True)
class Deprecated:
    """Encapsulate deprecation metadata for an endpoint.

    Attributes:
        message: Deprecation message to emit.
        stacklevel: Stack level to report for the warning.
    """

    message: str
    stacklevel: int = 4

    def __call__(self) -> None:
        """Emit a deprecation warning with the configured message."""
        warnings.warn(self.message, DeprecationWarning, stacklevel=self.stacklevel)


@dataclass(frozen=True)
class URLPath:
    """Hold a URL path template and the regex for extracting parameters."""

    pattern: ClassVar[re.Pattern] = re.compile(r"{(\w+)}")

    path: str

    @property
    def parameters(self) -> list[str]:
        """Return parameter names captured from the path template.

        Returns:
            list[str]: Parameter names extracted from the template.
        """
        return type(self).pattern.findall(self.path)

    def format(self, values: dict[str, Any]) -> str:
        """Return a formatted path with template parameters populated from a mapping.

        Args:
            values: Mapping of template parameter names to replacement values.

        Returns:
            str: The formatted path string.

        Raises:
            KeyError: If the mapping does not contain all template parameters.
        """
        self.validate_parameters(values)
        return self.path.format_map(values)

    def validate_parameters(self, values: dict[str, Any]) -> None:
        """Validate that a mapping includes all template parameters.

        Args:
            values: Mapping of template parameter names to replacement values.

        Raises:
            KeyError: If the mapping does not contain all template parameters.
        """
        if missing := set(self.parameters).difference(values):
            raise MissingPathArgumentsError(self.path, list(missing))

    def __str__(self):
        """Return the raw path template string."""
        return self.path


class EndpointContext:
    """Represent an API endpoint with an HTTP method and URL path pattern.

    Stores a method and a path template such as ``/v1/users/{user_id}``,
    wrapping the path in a ``URLPath`` helper for parameter extraction.
    A callable can be attached via ``func`` to implement the endpoint's
    request behavior.
    """

    def __init__(
        self, method: MethodType, path: str, decoder: Decoder | None = None, deprecated: DeprecatedType | None = None
    ) -> None:
        """Initialize the endpoint with an HTTP method and URL path template.

        Args:
            method: The HTTP method for the endpoint.
            path: The URL path template for the endpoint.
        """
        self.method = method
        self.path = path
        self.decoder = decoder
        self.deprecated = deprecated
        self._func: Callable[..., Any] | None = None
        self._signature: inspect.Signature | None = None
        self._return_type: Any | None = None

    def check_deprecation(self):
        if callable(self.deprecated):
            self.deprecated()

    @property
    def func(self) -> Callable[..., Any]:
        """Return the bound implementation callable for this endpoint.

        Returns:
            Callable[..., object]: The bound implementation callable.

        Raises:
            AttributeError: If the callable has not been set yet.
        """
        if self._func is None:
            raise AttributeError("_func is not set")
        return self._func

    @func.setter
    def func(self, value: Callable[..., Any]) -> None:
        """Bind an implementation callable to this endpoint.

        Args:
            value: The callable to bind to the endpoint.
        """
        self._func = value
        self._signature = inspect.signature(value)
        self._return_type = self._resolve_return_type()
        self._check_decoder()

    @property
    def signature(self) -> inspect.Signature:
        """Return the signature of the bound implementation callable.

        Raises:
            RuntimeError: If the callable signature has not been set yet.
        """
        if self._signature is None:
            raise RuntimeError("EndpointContext.signature is not set")
        return self._signature

    @property
    def path(self) -> URLPath:
        """Return the URL path wrapper for this endpoint.

        Returns:
            URLPath: The wrapped URL path template.
        """
        return self._path

    @path.setter
    def path(self, value: str):
        """Set the URL path template, wrapping it in ``URLPath``.

        Args:
            value: The URL path template string.
        """
        self._path = URLPath(value)

    @property
    def _decoder_required(self) -> bool:
        """Return whether a decoder is required for the endpoint's return type.

        Returns:
            bool: True when the return type is neither a response type nor
            ``None``; False otherwise.
        """
        return not (is_response_type(self.return_type) or is_none_type(self.return_type))

    def _check_decoder(self):
        """Validate decoder configuration against the resolved return type.

        Raises:
            MissingDecoderError: When the endpoint return type is not a
                response type and no decoder has been provided.
        """

        if self.decoder is None and self._decoder_required:
            raise MissingDecoderError(self.func)

    def _resolve_return_type(self) -> Any:
        """Resolve and return the endpoint's annotated return type.

        Returns:
            Any: The evaluated return type annotation, with forward references
                and typing forms resolved via the function's globals.

        Raises:
            MissingReturnTypeError: When the endpoint has no return annotation.
        """
        # No annotation
        if self.signature.return_annotation is inspect.Signature.empty:
            raise MissingReturnTypeError(self.func)

        # Evaluate forward refs + strings + typing forms using the function's globals
        return get_type_hints(self.func).get(
            "return",
            self.signature.return_annotation,
        )

    @property
    def return_type(self) -> Any:
        """Return the declared return type of the bound endpoint.

        If the callable does not declare a return annotation, the value may be
        ``inspect.Signature.empty``.

        Returns:
            Any: The return annotation of the bound callable.
        """
        return self._return_type


@dataclass
class EndpointsRegister:
    """Store and manage endpoint registrations.

    Attributes:
        registry: List of registered endpoint contexts.
    """

    registry: list[EndpointContext]

    @classmethod
    def default(cls: Type[EndpointsRegister]) -> EndpointsRegister:
        """Create an empty registry instance.

        Returns:
            EndpointsRegister: A registry with no registered endpoints.
        """
        return cls(registry=[])

    def register(self, endpoint: EndpointContext) -> None:
        """Register an endpoint context.

        Args:
            endpoint: The endpoint context to register.
        """
        self.registry.append(endpoint)


__all__ = ["EndpointContext", "EndpointsRegister", "Deprecated", "URLPath"]
