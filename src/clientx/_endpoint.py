"""The ``Endpoint`` the verb decorators build for each endpoint method.

The decorator in ``_method.py`` creates one ``Endpoint`` per decorated method when
the class body runs, and registers it in ``_registry.py``. It holds the decorator's
options and the analysed signature, and works out how the response is decoded, so the
function isn't inspected again at call time. When the client or resource class is
defined, ``_class_setup.py`` sets its ``owner``, joins a resource's prefix and tags onto
``raw_path`` and ``tags``, and calls ``set_up_request``.
"""

import functools
import inspect
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from types import NoneType
from typing import Any, get_origin

from httpx2 import USE_CLIENT_DEFAULT, Response, Timeout

from clientx._decoding import default_decoder, is_stream
from clientx._request import RequestPlan, plan_request
from clientx._signature import NO_VALUE, ParameterInfo, ParameterKind, SignatureInfo
from clientx._types import BuildRequestKwargs, Decoder, MethodType, UseClientDefault
from clientx.exceptions import DefinitionError


@dataclass(slots=True)
class Endpoint:
    """One endpoint: its HTTP method and path, the function that declares them, and its options.

    Attributes:
        method: The HTTP method, such as ``"GET"``.
        signature: The function's analysed signature, with every parameter as written.
            The first one receives the client or resource; ``parameters()`` returns the rest.
        tags: Tags that group endpoints, such as for ``clientx.tools``. A resource puts
            its own tags in front when its class is defined.
        raw_path: The path template, such as ``"/users/{user_id}"``. A resource joins its
            prefix onto it when its class is defined.
        decoder: Turns the ``httpx2.Response`` into the endpoint's return value. It's the
            decorator's ``decoder=``, or else ``__post_init__`` sets the one the return
            annotation implies. It stays ``None`` for ``-> None``: the endpoint returns nothing.
        deprecated: The message of the ``DeprecationWarning`` each call emits, such as
            ``"Use new() instead."``; ``None`` if the endpoint isn't deprecated.
        timeout: The request timeout for this endpoint, passed to httpx2 as it is, so it
            means what it does there: ``USE_CLIENT_DEFAULT`` (the default) uses the client's,
            and ``None`` turns the timeout off.
        raise_for_status: Whether a 4xx or 5xx response raises ``httpx2.HTTPStatusError``;
            ``None`` uses the client's setting.
        validate_arguments: Stored for argument validation, which isn't implemented
            yet (#136).
        stream_response: The decorator's ``stream=True``: the endpoint returns the open,
            unread response, which the caller reads and closes. Only with ``-> Response``,
            and without a ``decoder=``.
        owner: The client or resource class whose body declares the endpoint, or ``None``
            until that class is defined. An endpoint has one owner, so a resource joins
            its prefix once.
        request: How a call's arguments become the request, or ``None`` until the owner
            class is defined and calls ``set_up_request``.
        stream: Whether requests are sent in streaming mode: with ``stream_response``, or because
            the return annotation is an ``Iterator`` (``AsyncIterator`` for ``async def``).
            ``__post_init__`` sets it.
    """

    method: MethodType
    signature: SignatureInfo
    tags: list[str] | None = field(default=None)
    raw_path: str = field(default="")
    decoder: Decoder | None = field(default=None)
    deprecated: str | None = field(default=None)
    timeout: Timeout | float | None | UseClientDefault = field(default=USE_CLIENT_DEFAULT)
    raise_for_status: bool | None = field(default=None)
    validate_arguments: bool | None = field(default=None)
    stream_response: bool = field(default=False)
    owner: type | None = field(default=None)
    request: RequestPlan | None = field(default=None, init=False)
    stream: bool = field(init=False)

    def __post_init__(self) -> None:
        """Check the signature, and work out how the response is decoded, once, when the method is decorated.

        Raises:
            DefinitionError: If the parameters, the return annotation, ``stream=True`` or the
                ``decoder=`` can't work; see the ``_check_*`` methods and ``default_decoder``.
        """
        self._check_parameters()
        self._check_return_annotation()
        self._check_stream_response()
        self._check_decoder()

        name = self.signature.qualname
        returns = self.signature.returns
        is_async = self.signature.is_async
        try:
            self.stream = self.stream_response or is_stream(returns, is_async=is_async)
            if self.decoder is None:
                self.decoder = default_decoder(returns, is_async=is_async)
        except DefinitionError as error:
            raise DefinitionError(f"Endpoint '{name}': {error}") from error

    def _check_parameters(self) -> None:
        """Raise ``DefinitionError`` unless the first parameter is positional and none is ``*args`` or ``**kwargs``.

        The first parameter receives the client or resource, so a call must be able to pass it
        positionally. Every other parameter sends one value, which its annotation places in the
        request, so a ``*args`` or ``**kwargs`` parameter has nowhere to go.
        """
        name = self.signature.qualname
        first = self.signature.parameters[0] if self.signature.parameters else None
        if first is None or first.kind not in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL_OR_KEYWORD):
            raise DefinitionError(
                f"Endpoint '{name}' needs a positional first parameter, such as `self`, "
                "for the client or resource it's called on."
            )
        for parameter in self.parameters():
            if parameter.kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD):
                star = "*" if parameter.kind is ParameterKind.VAR_POSITIONAL else "**"
                raise DefinitionError(
                    f"Endpoint '{name}' can't take `{star}{parameter.name}`: each value it sends needs a "
                    "parameter of its own, which decides where the value goes in the request."
                )

    def _check_return_annotation(self) -> None:
        """Raise ``DefinitionError`` if there's no return annotation: it decides how the response is decoded."""
        if self.signature.returns.annotation is NO_VALUE:
            raise DefinitionError(
                f"Endpoint '{self.signature.qualname}' needs a return annotation, such as `-> None` or "
                "`-> User`: it decides what the endpoint returns."
            )

    def _check_stream_response(self) -> None:
        """Raise ``DefinitionError`` unless ``stream=True`` comes with ``-> Response`` and no ``decoder=``.

        The endpoint then returns the open response itself, so another return type has nothing
        to say, and a decoder would leave nobody sure who closes the response.
        """
        if not self.stream_response:
            return
        name = self.signature.qualname
        if self.signature.returns.base_type is not Response:
            raise DefinitionError(
                f"Endpoint '{name}' has stream=True, which returns the open response, so annotate it "
                "-> Response. An Iterator annotation, such as -> Iterator[bytes], streams the body by itself."
            )
        if self.decoder is not None:
            raise DefinitionError(
                f"Endpoint '{name}' has stream=True, which returns the open response, so it can't also take a decoder=."
            )

    def _check_decoder(self) -> None:
        """Raise ``DefinitionError`` if a ``decoder=`` can't return what the endpoint's annotation says.

        An endpoint annotated ``-> None`` returns nothing, so it takes no decoder. A decoder is
        a plain function that gets the response: the body is already read, or, for an endpoint
        annotated as a stream, the decoder returns the iterator. So it can't be ``async def``,
        and a generator decoder streams: a plain generator for a ``def`` endpoint annotated
        ``-> Iterator[...]``, an async generator for an ``async def`` one annotated
        ``-> AsyncIterator[...]``. A decoder that returns an iterator without being a generator
        can't be told apart here; type checkers check it against the annotation.
        """
        if self.decoder is None:
            return
        name = self.signature.qualname
        returns = self.signature.returns.base_type
        if returns is None or returns is NoneType:
            raise DefinitionError(
                f"Endpoint '{name}' is annotated -> None, so it returns nothing and can't take a decoder=. "
                "Annotate what the decoder returns."
            )
        function = _function_of(self.decoder)
        if inspect.iscoroutinefunction(function):
            raise DefinitionError(
                f"Endpoint '{name}': decoder= must be a plain function, not `async def`: the response is read "
                "before the decoder runs. To stream an `async def` endpoint, use an async generator, an "
                "`async def` with `yield`."
            )
        is_async = self.signature.is_async
        if inspect.isasyncgenfunction(function) and not is_async:
            raise DefinitionError(
                f"Endpoint '{name}' is a plain `def`, so its decoder can't be an async generator: use a "
                "generator, a `def` with `yield`."
            )
        if inspect.isgeneratorfunction(function) and is_async:
            raise DefinitionError(
                f"Endpoint '{name}' is `async def`, so its stream decoder must be an async generator, an "
                "`async def` with `yield`, not a plain generator."
            )
        streams = get_origin(returns) is (AsyncIterator if is_async else Iterator)
        if (inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function)) and not streams:
            iterator = "AsyncIterator" if is_async else "Iterator"
            raise DefinitionError(
                f"Endpoint '{name}': a generator decoder streams the response, so annotate the endpoint "
                f"-> {iterator}[...]."
            )

    def bind(self, owner: object, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return a call's arguments by parameter name, in signature order, with defaults filled in.

        ``owner``, the client or resource the endpoint was called on, fills the first
        parameter and is left out of the result.

        Raises:
            TypeError: If the arguments don't fit the signature, as in a normal call.
        """
        arguments = self.signature.bind(owner, *args, **kwargs)
        del arguments[self.signature.parameters[0].name]
        return arguments

    def parameters(self) -> tuple[ParameterInfo, ...]:
        """Return the endpoint's parameters, without the first one, which receives the client or resource."""
        return self.signature.parameters[1:]

    def set_up_request(self) -> None:
        """Work out, once, how a call's arguments become the request, and check the path against the parameters.

        ``_class_setup`` calls it when the owner class is defined, after joining a resource's
        prefix onto ``raw_path``: the prefix can add placeholders.

        Raises:
            DefinitionError: If the path template and the parameters don't fit together; see
                ``plan_request``.
        """
        try:
            self.request = plan_request(self.raw_path, self.parameters())
        except DefinitionError as error:
            raise DefinitionError(f"Endpoint '{self.signature.qualname}': {error}") from error

    def request_arguments(self, arguments: dict[str, Any]) -> tuple[str, BuildRequestKwargs]:
        """Return the URL path and the other ``build_request`` arguments for one call.

        The plan supplies the parts that carry the call's arguments; the endpoint adds its ``timeout``.

        Args:
            arguments: The call's arguments by parameter name, as ``bind`` returns them.

        Raises:
            DefinitionError: If the endpoint isn't declared in the body of a client or resource
                class, so it has no ``request`` plan.
            ArgumentError: If an argument's value can't be sent.
        """
        if self.request is None:
            raise DefinitionError(
                f"Endpoint '{self.signature.qualname}' can't be called: it isn't declared in the body of a "
                "ClientX, AsyncClientX, Resource or AsyncResource subclass."
            )
        url, request_arguments = self.request.build(arguments)
        request_arguments["timeout"] = self.timeout
        return url, request_arguments


def _function_of(decoder: Decoder) -> object:
    """Return the function a decoder runs: the decoder itself, or its class's ``__call__`` for an instance.

    ``inspect`` sees through functions, methods and ``functools.partial``, but not through a
    callable instance, so a decoder class with an ``async def __call__`` is checked by its method.
    """
    function: object = decoder
    if not (inspect.isroutine(decoder) or isinstance(decoder, functools.partial)):
        function = type(decoder).__call__
    return function
