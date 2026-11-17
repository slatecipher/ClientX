"""Inspect a callable's signature once, into plain data the rest of ClientX reads.

The decorator in ``_method.py`` calls ``inspect_signature`` on each endpoint method when
the class body runs. The result records each parameter's resolved annotation, its type
without ``Annotated``, and the request part a ``clientx.arguments`` helper marks it for,
so nothing reads annotations again at call time.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypeAliasType, get_args, get_origin, get_type_hints

from pydantic.fields import FieldInfo

from clientx._arguments import get_argument_spec
from clientx._types import HttpxArgument, HttpxArgumentSpec

ParameterKind = inspect._ParameterKind  # pyright: ignore[reportPrivateUsage]
"""A parameter's kind, such as positional-only or keyword-only. ``inspect`` has no public name for it."""

NO_VALUE = inspect.Parameter.empty
"""Marks a missing annotation or default, as ``inspect`` does. It's the same object as ``inspect.Signature.empty``."""

# Enough for any real chain of aliases, and a stop for cyclic ones such as `type A = B` with `type B = A`.
_MAX_ALIAS_DEPTH = 100


@dataclass(slots=True)
class ParameterInfo:
    """One parameter of an inspected callable.

    Only ``name``, ``position``, ``kind``, ``annotation`` and ``default`` are passed in;
    ``__post_init__`` derives the rest from ``annotation``.

    Attributes:
        name: The parameter's name.
        position: Its zero-based position in the signature.
        kind: Positional-only, positional-or-keyword, ``*args``, keyword-only, or ``**kwargs``.
        base_type: ``annotation`` without its ``Annotated`` wrapper or ``type`` alias, or
            ``NO_VALUE`` if there's no annotation.
        httpx_argument: The request part the parameter goes to, read from
            ``httpx_argument_spec``; ``None`` without one.
        httpx_argument_spec: The mark the helper adds to ``clientx_field_info``; ``None``
            without one.
        clientx_field_info: The ``FieldInfo`` of the parameter's ``clientx.arguments`` helper,
            such as ``Query()``, from the ``Annotated`` metadata; ``None`` without one. If
            there are several helpers, the last one wins. A plain ``Field(gt=0)`` isn't a
            helper, so it's skipped. A helper nested inside another type, such as
            ``Annotated[int, Query()] | None``, isn't found. Only the annotation is read, by
            design: a helper given as the default value isn't found, so there's no annotation
            and default to reconcile.
        annotation: The resolved annotation, with ``Annotated`` kept, or ``NO_VALUE`` if
            there's none.
        default: The default value, or ``NO_VALUE`` if there's none.
    """

    name: str
    position: int
    kind: ParameterKind
    base_type: Any = field(init=False)
    httpx_argument: HttpxArgument | None = field(default=None, init=False)
    httpx_argument_spec: HttpxArgumentSpec | None = field(default=None, init=False)
    clientx_field_info: FieldInfo | None = field(default=None, init=False)
    annotation: Any = NO_VALUE
    default: Any = NO_VALUE

    def __post_init__(self) -> None:
        """Derive ``base_type``, and the attributes that come from the helper, from ``annotation``."""
        base_type, metadata = unwrap_annotated(self.annotation)
        self.base_type = base_type
        self._set_clientx_field_info(metadata)

    def _set_clientx_field_info(self, metadata: tuple[Any, ...]) -> None:
        """Set ``clientx_field_info``, ``httpx_argument_spec`` and ``httpx_argument`` from the parameter's helper.

        The helper is the last ``FieldInfo`` in ``metadata`` that a ``clientx.arguments`` helper
        marked, so in ``Annotated[int, Query(), Header()]``, ``Header()`` wins. A plain ``FieldInfo``,
        such as ``Field(gt=0)``, is skipped. Without a helper, the three stay ``None``.

        Args:
            metadata: The ``Annotated`` metadata, in the order ``unwrap_annotated`` returns it:
                inner first, so a helper on the parameter wins over one from a ``type`` alias.
        """
        for meta in reversed(metadata):
            if isinstance(meta, FieldInfo):
                if httpx_meta := get_argument_spec(meta):
                    self.httpx_argument = httpx_meta.in_
                    self.httpx_argument_spec = httpx_meta
                    self.clientx_field_info = meta
                    break


@dataclass(frozen=True)
class ReturnInfo:
    """The return annotation of an inspected callable.

    Attributes:
        annotation: The resolved return annotation, with ``Annotated`` kept, or ``NO_VALUE``
            if there's none. ``-> None`` comes back as ``type(None)``, as
            ``typing.get_type_hints`` returns it.
        base_type: ``annotation`` without its ``Annotated`` wrapper or ``type`` alias.
        metadata: The ``Annotated`` metadata, or ``()``.
    """

    annotation: Any
    base_type: Any
    metadata: tuple[Any, ...]


@dataclass(frozen=True)
class SignatureInfo:
    """What ClientX needs from a callable's signature, read once.

    Attributes:
        func: The inspected callable, as given.
        name: Its ``__name__``, or its ``repr`` if it has none.
        qualname: Its ``__qualname__``, or its ``repr`` if it has none.
        module: Its ``__module__``, or ``None``.
        doc: Its docstring, cleaned up by ``inspect.getdoc``, or ``None``.
        is_async: Whether it's an ``async def`` function, after following ``__wrapped__``.
        parameters: One ``ParameterInfo`` per parameter, in order.
        returns: The return annotation.
        signature: The signature from ``inspect.signature``, with annotations as written
            (not resolved). ``bind`` uses it.
    """

    func: Callable[..., Any]
    name: str
    qualname: str
    module: str | None
    doc: str | None
    is_async: bool
    parameters: tuple[ParameterInfo, ...]
    returns: ReturnInfo
    signature: inspect.Signature = field(repr=False)

    def bind(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Bind a call's arguments to the signature, with defaults filled in.

        Returns:
            Each parameter's value by name, in signature order. A ``*args`` parameter gets
            a tuple and a ``**kwargs`` parameter a dict, empty when the call passes none.

        Raises:
            TypeError: If the arguments don't fit the signature, as in a normal call.
        """
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return bound.arguments


def unwrap_annotated(type_hint: Any) -> tuple[Any, tuple[Any, ...]]:
    """Split an ``Annotated`` type hint into its underlying type and its metadata.

    A ``type`` alias is expanded, whether it's the whole hint or the type inside an
    ``Annotated``, so ``Annotated`` metadata inside one is found too. Nested ``Annotated``
    hints are flattened into one tuple, inner metadata first, the order Python uses when
    it flattens them itself. A hint that isn't ``Annotated`` comes back with empty metadata::

        unwrap_annotated(Annotated[int, Range(1, 10), Doc("id")])
            -> (int, (Range(1, 10), Doc("id")))
        unwrap_annotated(UserId)  # type UserId = Annotated[int, Doc("id")]
            -> (int, (Doc("id"),))
        unwrap_annotated(str)
            -> (str, ())
    """
    collected_metadata: tuple[Any, ...] = ()
    type_hint = _unwrap_type_alias(type_hint)
    while get_origin(type_hint) is Annotated:
        underlying_type, *metadata_items = get_args(type_hint)
        # Prepend: metadata from an alias inside comes before this level's, as in a nested Annotated.
        collected_metadata = (*metadata_items, *collected_metadata)
        type_hint = _unwrap_type_alias(underlying_type)
    return type_hint, collected_metadata


def _unwrap_type_alias(annotation: Any) -> Any:
    """Replace a PEP 695 ``type`` alias, plain or generic, with the type it stands for.

    ``type UserId = Annotated[int, ...]`` becomes ``Annotated[int, ...]``, and
    ``QueryT[int]`` for ``type QueryT[T] = Annotated[T, ...]`` becomes
    ``Annotated[int, ...]``. Python expands plain assignment aliases itself, but not
    these, so their ``Annotated`` metadata would otherwise be lost.
    """
    for _ in range(_MAX_ALIAS_DEPTH):
        if isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
        elif isinstance(alias := get_origin(annotation), TypeAliasType):
            try:
                annotation = alias.__value__[get_args(annotation)]
            except TypeError:
                # The alias's value can't take the arguments (for example `type X[T] = int`).
                annotation = alias.__value__
        else:
            break
    return annotation


def _resolve_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """Return the callable's type hints, with string annotations evaluated and ``Annotated`` kept.

    It reads the hints of the function ``func`` wraps, following ``__wrapped__``.
    ``include_extras=True`` keeps the ``Annotated`` wrappers that ``typing.get_type_hints``
    would otherwise strip.

    Raises:
        NameError: If an annotation names something that isn't defined yet. For an endpoint
            that's checked when its class body runs, so a model defined further down the
            module isn't found. Other errors from ``typing.get_type_hints`` propagate too.
    """
    return get_type_hints(inspect.unwrap(func), include_extras=True)


def inspect_signature(func: Callable[..., Any]) -> SignatureInfo:
    """Inspect a callable once and return what ClientX needs from its signature.

    Every parameter is described as written, including a ``self`` parameter: what a
    parameter means, such as the first one of an endpoint, is up to the caller.

    Args:
        func: The callable to inspect. A ``functools.wraps`` wrapper is read through to
            the function it wraps.

    Returns:
        The callable's ``SignatureInfo``.

    Raises:
        NameError: If an annotation names something that isn't defined yet.
        ValueError: If ``inspect.signature`` can't find a signature, as for some builtins.
        TypeError: If ``func`` is an object ``inspect.signature`` doesn't support.
    """
    signature = inspect.signature(func)
    resolved_type_hints = _resolve_type_hints(func)

    parameters: list[ParameterInfo] = [
        ParameterInfo(
            name=raw_parameter.name,
            position=position,
            kind=raw_parameter.kind,
            annotation=resolved_type_hints.get(raw_parameter.name, raw_parameter.annotation),
            default=raw_parameter.default,
        )
        for position, raw_parameter in enumerate(signature.parameters.values())
    ]

    return_annotation = resolved_type_hints.get("return", signature.return_annotation)
    return_base_type, return_metadata = unwrap_annotated(return_annotation)

    original_function = inspect.unwrap(func)

    return SignatureInfo(
        func=func,
        name=getattr(func, "__name__", repr(func)),
        qualname=getattr(func, "__qualname__", repr(func)),
        module=getattr(func, "__module__", None),
        doc=inspect.getdoc(func),
        is_async=inspect.iscoroutinefunction(original_function),
        parameters=tuple(parameters),
        returns=ReturnInfo(return_annotation, return_base_type, return_metadata),
        signature=signature,
    )
