from __future__ import annotations

import inspect
import json
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from inspect import BoundArguments
from types import MappingProxyType
from typing import Any, ClassVar, get_type_hints
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.errors import PydanticSchemaGenerationError
from pydantic_core import to_jsonable_python

from clientx._annotation_extractor import NamedAnnotation, NamedAnnotationExtractor, model_annotations
from clientx._annotations import PathParam
from clientx._client import AsyncClientX, AsyncResource, ClientX, Resource
from clientx._client_types import (
    Decoder,
    DeprecatedType,
    MethodType,
    is_none_type,
    is_response_type,
)
from clientx.decoders import AsyncStreamDecoder, StreamDecoder, StreamResponseDecoder
from clientx.exceptions import (
    ArgumentValidationError,
    EndpointSignatureError,
    MissingDecoderError,
    MissingPathArgumentsError,
    MissingReturnTypeError,
    PathTemplateError,
    PathValueError,
)

# The sync stream decoders ClientX ships, each with an async counterpart named "Async" + its name.
_BUILT_IN_STREAM_DECODERS = frozenset({"StreamLinesDecoder", "StreamChunksDecoder"})

_POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)

# `quote` leaves dots alone, but a whole segment of `.` or `..` would be resolved as a dot segment.
_DOT_SEGMENTS = {".": "%2E", "..": "%2E%2E"}

# Placeholder converters: none sends the value as one segment; `path` keeps its slashes.
_CONVERTERS = frozenset({"path"})


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


def _encode_path_value(path: str, name: str, value: object, *, keep_slashes: bool) -> str:
    """Return ``value`` as percent-encoded path text for placeholder ``name`` in ``path``.

    The value is converted like a query value: an ``Enum`` becomes its value, a
    ``datetime`` ISO 8601, a ``UUID`` its string, and a number or boolean JSON text
    (``2``, ``true``). Any other object uses ``str``. Every character that isn't
    unreserved is then percent-encoded, slashes included unless ``keep_slashes``, so
    a value can't add path segments, a query string, or a fragment. A ``.`` or ``..``
    segment is encoded too, so it can't move up the path.

    Raises:
        PathValueError: The value is ``None``, is empty, or (with ``keep_slashes``) has an
            empty segment. Each would change the path: ``/users/{id}`` with ``""`` would
            call ``/users/``, and a doubled slash can make the rest look like a host name.
    """
    if value is None:
        raise PathValueError(path, name, value, "None would be sent as 'null'")
    jsonable = to_jsonable_python(value, fallback=str)
    text = jsonable if isinstance(jsonable, str) else json.dumps(jsonable)
    if not text:
        raise PathValueError(path, name, value, "an empty value would remove the segment and call a different path")
    segments = text.split("/") if keep_slashes else [text]
    if "" in segments:
        problem = "a leading, trailing, or doubled slash leaves an empty segment, which would change the path"
        raise PathValueError(path, name, value, problem)
    return "/".join(_DOT_SEGMENTS.get(segment) or quote(segment, safe="") for segment in segments)


@dataclass(frozen=True)
class URLPath:
    """Hold a URL path template and render it with encoded values.

    A placeholder is ``{name}``, sent as one path segment, or ``{name:path}``, which
    keeps slashes in the value for multi-segment values such as file paths. ``{{``
    and ``}}`` are literal braces.

    Raises:
        PathTemplateError: A placeholder has a converter other than ``path``.
    """

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\{\{|\}\}|\{(\w+)(?::(\w*))?\}")

    path: str

    def __post_init__(self) -> None:
        """Reject unknown converters, so a typo fails when the class is defined."""
        for match in type(self).pattern.finditer(self.path):
            name, converter = match.groups()
            if converter is not None and converter not in _CONVERTERS:
                raise PathTemplateError(self.path, f"placeholder {{{name}:{converter}}} has an unknown converter")

    @property
    def parameters(self) -> list[str]:
        """Return parameter names captured from the path template.

        Returns:
            list[str]: Parameter names extracted from the template.
        """
        return [name for name, _ in type(self).pattern.findall(self.path) if name]

    def format(self, values: dict[str, Any]) -> str:
        """Return the path with each placeholder replaced by its encoded value.

        Args:
            values: Mapping of template parameter names to replacement values.

        Returns:
            str: The formatted path string.

        Raises:
            MissingPathArgumentsError: If the mapping does not contain all template parameters.
            PathValueError: If a value is ``None``, is empty, or has an empty segment in a
                ``{name:path}`` placeholder.
        """
        self.validate_parameters(values)

        def render(match: re.Match[str]) -> str:
            name, converter = match.groups()
            if name is None:
                return match.group()[0]
            return _encode_path_value(self.path, name, values[name], keep_slashes=converter == "path")

        return type(self).pattern.sub(render, self.path)

    def validate_parameters(self, values: dict[str, Any]) -> None:
        """Validate that a mapping includes all template parameters.

        Args:
            values: Mapping of template parameter names to replacement values.

        Raises:
            MissingPathArgumentsError: If the mapping does not contain all template parameters.
        """
        if missing := set(self.parameters).difference(values):
            raise MissingPathArgumentsError(self.path, list(missing))

    def __str__(self) -> str:
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
        validate_arguments: bool | None = None,
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
            validate_arguments: Whether arguments are checked against their
                annotations before a request is sent. ``None`` (the default)
                follows the client's ``validate_arguments``.
        """
        # One validator per parameter, built on the first validated call; None for a type Pydantic can't validate.
        self._validators: dict[str, TypeAdapter[Any] | None] = {}
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
        self.validate_arguments = validate_arguments
        # Dedupe tags while preserving insertion order.
        self.tags = list(dict.fromkeys(tags or []))
        # The client or resource class whose body the endpoint is in. A resource joins its prefix onto the
        # endpoint's path, so an endpoint can belong to only one class.
        self.owner: type | None = None

    def __repr__(self) -> str:
        """Return a dataclass-like summary of the endpoint configuration."""
        func_qualname = self._func.__qualname__ if self._func is not None else None
        return (
            f"{type(self).__name__}(method={self.method!r}, path={str(self.path)!r}, "
            f"function={func_qualname!r}, has_decoder={self.decoder is not None!r}, "
            f"deprecated={self.deprecated is not None!r}, stream={self.stream!r}, "
            f"timeout={self.timeout!r}, raise_for_status={self.raise_for_status!r}, "
            f"validate_arguments={self.validate_arguments!r}, tags={self.tags!r}, "
            f"return_type={_type_name(self._return_type)!r})"
        )

    def check_deprecation(self) -> None:
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

        The decoder decides: ``StreamDecoder`` and ``AsyncStreamDecoder`` subclasses
        (such as ``StreamLinesDecoder``) and ``StreamResponseDecoder`` stream; any other
        decoder, or no decoder, does not.

        Returns:
            bool: True when the endpoint's decoder needs a streamed response.
        """
        return isinstance(self.decoder, StreamDecoder | AsyncStreamDecoder | StreamResponseDecoder)

    @property
    def is_async(self) -> bool:
        """Return whether the endpoint is an ``async def`` method, for an ``AsyncClientX``.

        Returns:
            bool: True when calling the endpoint returns an awaitable.
        """
        return inspect.iscoroutinefunction(self.func)

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
            EndpointSignatureError: The first parameter isn't positional, there's
                a ``*args`` or ``**kwargs`` parameter, or an ``async def`` endpoint's
                decoder streams synchronously.
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
    def path(self, value: str) -> None:
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

    def check_path_helpers(self) -> None:
        """Raise ``EndpointSignatureError`` if a ``PathParam()`` parameter has no placeholder in the path.

        Called by ``ClientX`` and ``Resource`` once the class body is done, because a
        ``Resource`` prefix can add a placeholder after the method is decorated.
        """
        placeholders = set(self.path.parameters)
        for name, annotation in self.parameters.items():
            if isinstance(annotation.part, PathParam) and name not in placeholders:
                raise EndpointSignatureError(
                    self.func,
                    f"marks {name!r} with PathParam(), but its path {str(self.path)!r} has no {{{name}}} placeholder",
                )

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

    def _check_decoder(self) -> None:
        """Validate decoder configuration against the resolved return type.

        Raises:
            MissingDecoderError: When the endpoint return type is not a
                response type and no decoder has been provided.
            EndpointSignatureError: When a stream decoder is for the other kind
                of endpoint: a ``StreamDecoder`` on an ``async def`` endpoint, or an
                ``AsyncStreamDecoder`` on a ``def`` endpoint.
        """

        if self.decoder is None and self._decoder_required:
            raise MissingDecoderError(self.func)
        name = type(self.decoder).__name__
        if self.is_async and isinstance(self.decoder, StreamDecoder):
            fix = f"Async{name}" if name in _BUILT_IN_STREAM_DECODERS else "an AsyncStreamDecoder subclass"
            raise EndpointSignatureError(
                self.func,
                f"is `async def`, but its decoder, {name}, streams synchronously, for `def` endpoints. Use {fix}",
            )
        if not self.is_async and isinstance(self.decoder, AsyncStreamDecoder):
            sync_name = name.removeprefix("Async")
            fix = sync_name if sync_name in _BUILT_IN_STREAM_DECODERS else "a StreamDecoder subclass"
            raise EndpointSignatureError(
                self.func,
                f"is a plain `def`, but its decoder, {name}, streams asynchronously, for `async def` endpoints. "
                f"Use {fix}",
            )

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

    def bind(
        self,
        client: ClientX | AsyncClientX | Resource | AsyncResource,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        validate: bool = False,
    ) -> BoundArguments:
        """Bind call arguments to the endpoint function signature.

        This helper binds the provided ``client``, positional arguments, and
        keyword arguments against the endpoint's captured signature, then
        applies default values.

        Args:
            client: Client or mounted resource passed as the first argument (``self``).
            args: Positional arguments supplied by the caller.
            kwargs: Keyword arguments supplied by the caller.
            validate: Check each argument the caller passed against its parameter's
                annotation, before defaults are applied. Defaults aren't checked.

        Returns:
            BoundArguments: Bound argument mapping with defaults applied.

        Raises:
            RuntimeError: If the endpoint signature has not been captured yet.
            TypeError: If the provided arguments do not satisfy the function
                signature.
            ArgumentValidationError: If ``validate`` is set and an argument doesn't
                match its annotation.
        """
        bound = self.signature.bind(client, *args, **kwargs)
        if validate:
            self._validate(bound.arguments)
        bound.apply_defaults()

        return bound

    def _validate(self, arguments: dict[str, Any]) -> None:
        """Check each request argument against its parameter's full annotation, strictly.

        Strict mode rejects what a type checker would (``"1"`` for ``int``), and the
        validated value is thrown away, so validation never changes what's sent.
        """
        for name, value in arguments.items():
            if name == self.client_parameter:
                continue
            validator = self._validator(name)
            if validator is None:
                continue
            try:
                validator.validate_python(value, strict=True)
            except ValidationError as error:
                raise ArgumentValidationError(self.func, name, error) from error

    def _validator(self, name: str) -> TypeAdapter[Any] | None:
        """Return the cached validator for parameter ``name``, building it on first use.

        Unannotated parameters, and types Pydantic can't validate (such as
        ``BinaryIO``), get ``None`` and aren't checked.
        """
        if name not in self._validators:
            annotation = self.signature.parameters[name].annotation
            validator: TypeAdapter[Any] | None = None
            if annotation is not inspect.Parameter.empty:
                try:
                    validator = TypeAdapter(annotation)
                except PydanticSchemaGenerationError:
                    validator = None
            self._validators[name] = validator
        return self._validators[name]


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
