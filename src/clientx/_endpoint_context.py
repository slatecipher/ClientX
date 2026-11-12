from __future__ import annotations

import inspect
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from inspect import BoundArguments
from types import MappingProxyType
from typing import Any, ClassVar, get_type_hints

import httpx2
from pydantic import BaseModel

from clientx._annotation_extractor import NamedAnnotation, NamedAnnotationExtractor, model_annotations
from clientx._client import ClientX, Resource
from clientx._client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.decoders import StreamDecoder, StreamResponseDecoder
from clientx.exceptions import (
    EndpointSignatureError,
    MissingDecoderError,
    MissingPathArgumentsError,
    MissingReturnTypeError,
)

_POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


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
    decorator. When a callable is assigned via ``func``, the endpoint analyses it
    once, the way FastAPI analyses a route when it's registered: it captures the
    signature with annotations resolved, the return type, and each request
    parameter's annotation. Calls then only bind arguments and look this up.
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
        self._func: Callable[..., Any] | None = None
        self._signature: inspect.Signature | None = None
        self._return_type: Any | None = None
        self._client_parameter: str | None = None
        self._parameters: MappingProxyType[str, NamedAnnotation] | None = None
        self.method = method
        self.path = path
        self.decoder = decoder
        self.deprecated = deprecated
        self.timeout = timeout
        self.raise_for_status = raise_for_status
        # Dedupe tags while preserving insertion order.
        self.tags = list(dict.fromkeys(tags or []))

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
        """Bind an implementation callable to this endpoint, and analyse it once.

        Everything that can be wrong with the function raises here, when the class is
        defined, rather than on the first call.

        Args:
            value: The callable to bind to the endpoint.

        Raises:
            MissingReturnTypeError: The function has no return annotation.
            MissingDecoderError: The return type needs a decoder and none was given.
            EndpointSignatureError: The first parameter isn't positional, or there's
                a ``*args`` or ``**kwargs`` parameter.
            MisplacedHelperError: A helper is nested inside another type, or a
                parameter has two, here or in a model a parameter is annotated with.
            MissingPathArgumentsError: A path placeholder names no parameter.
        """
        self._func = value
        self._signature = inspect.signature(value)
        self._return_type = self._resolve_return_type()
        self._check_decoder()
        self._signature = _with_resolved_annotations(value, self._signature)
        self._client_parameter, self._parameters = _analyse_parameters(value, self._signature)
        self._check_path()

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
    def client_parameter(self) -> str:
        """Return the name of the first parameter, which receives the client or resource.

        Raises:
            RuntimeError: If the callable has not been set yet.
        """
        if self._client_parameter is None:
            raise RuntimeError("Endpoint.client_parameter is not set")
        return self._client_parameter

    @property
    def parameters(self) -> MappingProxyType[str, NamedAnnotation]:
        """Return the request parameters (all but the first) and their annotations, in order.

        Analysed once, when ``func`` is set, so a call doesn't read annotations again.

        Raises:
            RuntimeError: If the callable has not been set yet.
        """
        if self._parameters is None:
            raise RuntimeError("Endpoint.parameters is not set")
        return self._parameters

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

        Once ``func`` is set, the new path's placeholders are checked against its
        parameters, so a ``Resource`` prefix with a placeholder no parameter fills
        raises when the resource class is defined.

        Args:
            value: The URL path template string.

        Raises:
            MissingPathArgumentsError: A placeholder names no request parameter.
        """
        self._path = URLPath(value)
        if self._func is not None:
            self._check_path()

    def _check_path(self) -> None:
        """Raise ``MissingPathArgumentsError`` if a placeholder names no request parameter."""
        if missing := [name for name in self.path.parameters if name not in self.parameters]:
            raise MissingPathArgumentsError(str(self.path), missing, func=self.func)

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


def _with_resolved_annotations(func: Callable[..., Any], signature: inspect.Signature) -> inspect.Signature:
    """Return ``signature`` with its parameter annotations evaluated, ``Annotated`` metadata kept.

    With ``from __future__ import annotations``, ``inspect.signature`` gives annotations
    as strings, and a helper inside one would be lost.
    """
    hints = get_type_hints(func, include_extras=True)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=hints.get(name, parameter.annotation))
            for name, parameter in signature.parameters.items()
        ]
    )


def _analyse_parameters(
    func: Callable[..., Any], signature: inspect.Signature
) -> tuple[str, MappingProxyType[str, NamedAnnotation]]:
    """Return the client parameter's name and each request parameter's annotation.

    Also checks the helpers on each parameter, and on the fields of a model a
    parameter is annotated with, so misplaced ones raise when the class is defined.
    """
    parameters = list(signature.parameters.values())
    if not parameters or parameters[0].kind not in _POSITIONAL:
        raise EndpointSignatureError(
            func, "must take the client or resource as its first, positional parameter (usually `self`)"
        )
    client, *rest = parameters
    for parameter in rest:
        if parameter.kind in _VARIADIC:
            star = "*" if parameter.kind is inspect.Parameter.VAR_POSITIONAL else "**"
            raise EndpointSignatureError(
                func, f"can't take `{star}{parameter.name}`: give each request value a named parameter"
            )

    annotations = NamedAnnotationExtractor.from_signature(signature)
    del annotations[client.name]
    for annotation in annotations.values():
        model = annotation.info.annotation
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__pydantic_complete__:
            model_annotations(model)
    return client.name, MappingProxyType(annotations)


__all__ = ["Endpoint", "DeprecatedMessage", "URLPath"]
