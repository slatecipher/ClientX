from __future__ import annotations

import inspect
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from inspect import BoundArguments
from typing import Any, ClassVar, get_type_hints

import httpx2

from clientx._annotation_extractor import AnnotationExtractor
from clientx._client import ClientX, Resource
from clientx._client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.decoders import StreamDecoder, StreamResponseDecoder
from clientx.exceptions import MissingDecoderError, MissingPathArgumentsError, MissingReturnTypeError


def _type_name(annotation: Any) -> str | None:
    """Return a readable name for a resolved return annotation, or ``None`` if unset.

    Plain classes use their ``__qualname__`` (``"User"``). Everything else, such as
    generic aliases (``list[User]``) and unions (``User | None``), has no
    ``__qualname__`` of its own, so its ``repr`` is used instead.
    """
    if annotation is None:
        return None
    if isinstance(annotation, type):
        return annotation.__qualname__
    return repr(annotation)


@dataclass(frozen=True)
class DeprecatedMessage:
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

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"{(\w+)}")

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


class Endpoint:
    """Represent a decorated endpoint with metadata and binding helpers.

    An endpoint stores the HTTP method, URL path template, optional decoder,
    optional deprecation handler, and optional metadata tags configured by the
    decorator. When a callable is assigned via ``func``, the endpoint captures
    the function signature and resolved return type so calls can be validated
    and bound before request construction.
    """

    def __init__(
        self,
        method: MethodType,
        path: str,
        decoder: Decoder | None = None,
        deprecated: DeprecatedType | None = None,
        tags: list[str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        raise_for_status: bool | None = None,
    ) -> None:
        """Initialize endpoint metadata from decorator configuration.

        Args:
            method: HTTP method used for requests to this endpoint.
            path: URL path template, optionally containing ``{parameter}``
                placeholders.
            decoder: Optional response decoder for non-``Response`` return
                types. Defaults to None.
            deprecated: Optional callable or deprecation metadata emitted when
                the endpoint is invoked. Defaults to None.
            tags: Optional metadata labels, which ``clientx.tools.list_tools`` can
                filter by. Defaults to None.
            timeout: Optional request timeout override for this endpoint.
                Defaults to None.
            raise_for_status: Whether a 4xx or 5xx response raises
                ``httpx2.HTTPStatusError``. ``None`` (the default) follows the
                client's ``raise_for_status``.
        """
        self.method = method
        self.path = path
        self.decoder = decoder
        self.deprecated = deprecated
        self.timeout = timeout
        self.raise_for_status = raise_for_status
        # Dedupe tags while preserving insertion order.
        self.tags = list(dict.fromkeys(tags or []))
        self._func: Callable[..., Any] | None = None
        self._signature: inspect.Signature | None = None
        self._return_type: Any | None = None

    def __repr__(self) -> str:
        """Return a dataclass-like summary of the endpoint configuration."""
        func_qualname = self._func.__qualname__ if self._func is not None else None
        return (
            f"{type(self).__name__}(method={self.method!r}, path={str(self.path)!r}, "
            f"function={func_qualname!r}, has_decoder={self.decoder is not None!r}, "
            f"deprecated={self.deprecated is not None!r}, stream={self.stream!r}, "
            f"timeout={self.timeout!r}, raise_for_status={self.raise_for_status!r}, tags={self.tags!r}, "
            f"return_type={_type_name(self._return_type)!r})"
        )

    def check_deprecation(self):
        """Emit a deprecation warning when a deprecation handler is configured.

        Calls ``self.deprecated`` when it is callable, allowing either a plain
        callable or ``DeprecatedMessage`` to handle warning emission.

        Returns:
            None
        """
        if callable(self.deprecated):
            self.deprecated()

    @property
    def stream(self) -> bool:
        """Return whether requests to this endpoint are sent in streaming mode.

        The decoder decides: ``StreamDecoder`` subclasses (such as
        ``StreamLinesDecoder``) and ``StreamResponseDecoder`` stream; any other
        decoder, or no decoder, does not.

        Returns:
            bool: True when the endpoint's decoder needs a streamed response.
        """
        return isinstance(self.decoder, StreamDecoder | StreamResponseDecoder)

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
        # Raises MisplacedHelperError when the class is defined, not on the first call.
        AnnotationExtractor.from_signature(self._signature)

    @property
    def signature(self) -> inspect.Signature:
        """Return the signature of the bound implementation callable.

        Returns:
            inspect.Signature: Signature captured from the bound endpoint
                function.

        Raises:
            RuntimeError: If the callable signature has not been set yet.
        """
        if self._signature is None:
            raise RuntimeError("Endpoint.signature is not set")
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

        The value is ``None`` until ``func`` is assigned.

        Returns:
            Any: Resolved return type for the bound callable, or ``None`` when
                unbound.
        """
        return self._return_type

    def bind(self, client: ClientX | Resource, args: tuple[Any, ...], kwargs: dict[str, Any]) -> BoundArguments:
        """Bind call arguments to the endpoint function signature.

        This helper binds the provided ``client``, positional arguments, and
        keyword arguments against the endpoint's captured signature, then
        applies default values.

        Args:
            client: Client or mounted resource passed as the first argument (``self``).
            args: Positional arguments supplied by the caller.
            kwargs: Keyword arguments supplied by the caller.

        Returns:
            BoundArguments: Bound argument mapping with defaults applied.

        Raises:
            RuntimeError: If the endpoint signature has not been captured yet.
            TypeError: If the provided arguments do not satisfy the function
                signature.
        """
        bound = self.signature.bind(client, *args, **kwargs)
        bound.apply_defaults()

        return bound


__all__ = ["Endpoint", "DeprecatedMessage", "URLPath"]
