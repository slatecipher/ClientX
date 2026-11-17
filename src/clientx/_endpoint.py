"""The ``Endpoint`` the verb decorators build for each endpoint method.

The decorator in ``_method.py`` creates one ``Endpoint`` per decorated method when
the class body runs, and registers it in ``_registry.py``. It holds the decorator's
options and the analysed signature, and works out how the response is decoded, so the
function isn't inspected again at call time. When the client or resource class is
defined, ``_class_setup.py`` sets its ``owner``, joins a resource's prefix and tags onto
``raw_path`` and ``tags``, and calls ``set_up_request``.
"""

from dataclasses import dataclass, field
from typing import Any

from httpx2 import USE_CLIENT_DEFAULT, Timeout

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
        validate_arguments: Whether arguments are checked against their annotations
            before sending; ``None`` uses the client's setting.
        owner: The client or resource class whose body declares the endpoint, or ``None``
            until that class is defined. An endpoint has one owner, so a resource joins
            its prefix once.
        request: How a call's arguments become the request, or ``None`` until the owner
            class is defined and calls ``set_up_request``.
        stream: Whether requests are sent in streaming mode, because the return annotation
            is an ``Iterator`` (``AsyncIterator`` for ``async def``). ``__post_init__`` sets it.
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
    owner: type | None = field(default=None)
    request: RequestPlan | None = field(default=None, init=False)
    stream: bool = field(init=False)

    def __post_init__(self) -> None:
        """Check the signature, and work out how the response is decoded, once, when the class is defined.

        Raises:
            DefinitionError: If the function has no positional first parameter for the client or
                resource (it has none, or it's keyword-only, ``*args`` or ``**kwargs``), has no
                return annotation, or has one that can't be decoded without a ``decoder=``.
        """
        name = self.signature.qualname
        first = self.signature.parameters[0] if self.signature.parameters else None
        if first is None or first.kind not in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL_OR_KEYWORD):
            raise DefinitionError(
                f"Endpoint '{name}' needs a positional first parameter, such as `self`, "
                "for the client or resource it's called on."
            )

        returns = self.signature.returns
        if returns.annotation is NO_VALUE:
            raise DefinitionError(
                f"Endpoint '{name}' needs a return annotation, such as `-> None` or `-> User`: "
                "it decides what the endpoint returns."
            )
        is_async = self.signature.is_async
        try:
            self.stream = is_stream(returns, is_async=is_async)
            if self.decoder is None:
                self.decoder = default_decoder(returns, is_async=is_async)
        except DefinitionError as error:
            raise DefinitionError(f"Endpoint '{name}': {error}") from error

    def bind(self, owner: object, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Match a call's arguments to the endpoint's parameters, with defaults filled in.

        Args:
            owner: The object the endpoint was called on: a client, or a resource
                mounted on one. It fills the first parameter and is left out of the result.
            *args: The call's positional arguments.
            **kwargs: The call's keyword arguments.

        Returns:
            Each remaining parameter's value by name, in signature order.

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
