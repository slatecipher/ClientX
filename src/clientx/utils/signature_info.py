"""
describe_signature: turn any callable into a SignatureInfo.

This module holds the inspection logic: reading the signature, resolving string and
forward-reference type hints, splitting out Annotated metadata, and working out which
class (if any) owns the callable. The result objects themselves live in models.py.
"""
from __future__ import annotations

import inspect
import sys
import typing
from typing import Any, Callable

from clientx.utils.models import MethodKind, ParameterInfo, ReturnInfo, SignatureInfo
from clientx.utils.type_hints import unwrap_annotated


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def describe_signature(func: Callable[..., Any]) -> SignatureInfo:
    """
    Inspect `func` and return a SignatureInfo describing it.

    Supported callables:
      - Plain and async functions
      - Decorated functions, provided the decorator uses functools.wraps
      - Instance methods, class methods, and static methods, bound or unbound
      - Classes, which are described through their __init__

    Type hints written as strings or forward references are resolved where possible.
    If a hint can't be resolved, the raw annotation is kept rather than raising.

    Each call inspects `func` from scratch and returns a new SignatureInfo, so two
    calls on the same function give equal but separate objects.

    Args:
        func: The callable to describe.

    Returns:
        A SignatureInfo with the callable's parameters, return type, Annotated
        metadata, and owning class (if any).

    Raises:
        ValueError: If Python can't produce a signature for `func`, as with some
            built-ins implemented in C.
        TypeError: If `func` isn't callable.
    """
    return _build_signature_info(func)

# --------------------------------------------------------------------------- #
# Internals: building a SignatureInfo
# --------------------------------------------------------------------------- #
def _build_signature_info(func: Callable[..., Any]) -> SignatureInfo:
    """Read the signature and type hints of `func` and assemble a SignatureInfo."""
    signature = inspect.signature(func)
    resolved_type_hints = _resolve_type_hints(func)

    parameters: list[ParameterInfo] = []
    for position, raw_parameter in enumerate(signature.parameters.values()):
        annotation = resolved_type_hints.get(raw_parameter.name, raw_parameter.annotation)
        base_type, metadata = unwrap_annotated(annotation)
        parameters.append(ParameterInfo(
            name=raw_parameter.name,
            position=position,
            kind=raw_parameter.kind,
            annotation=annotation,
            base_type=base_type,
            metadata=metadata,
            default=raw_parameter.default,
        ))

    return_annotation = resolved_type_hints.get("return", signature.return_annotation)
    return_base_type, return_metadata = unwrap_annotated(return_annotation)
    original_function = inspect.unwrap(func)  # look through functools.wraps decorators
    method_kind, owner, bound_to = _resolve_ownership(func)

    return SignatureInfo(
        func=func,
        name=getattr(func, "__name__", repr(func)),
        qualname=getattr(func, "__qualname__", repr(func)),
        module=getattr(func, "__module__", None),
        doc=inspect.getdoc(func),
        is_async=inspect.iscoroutinefunction(original_function),
        method_kind=method_kind,
        owner=owner,
        bound_to=bound_to,
        parameters=tuple(parameters),
        returns=ReturnInfo(return_annotation, return_base_type, return_metadata),
        signature=signature,
    )

def _resolve_ownership(func: Callable[..., Any]) -> tuple[MethodKind, type | None, Any]:
    """
    Work out which class owns `func` and what kind of method it is.

    Returns:
        (method_kind, owner, bound_to)

    Python only keeps a live link to the class for bound methods (via __self__).
    For anything else, accessing `SomeClass.method` gives back a plain function, so
    the owner is found by following the function's __qualname__ (for example
    "UserService.create") from its module. The method kind is then read from the
    raw class attribute, since that is the only place the @staticmethod or
    @classmethod wrapper is still visible.
    """
    if inspect.isclass(func):
        return MethodKind.CONSTRUCTOR, func, None

    if inspect.ismethod(func):
        bound_to = func.__self__
        underlying_function = func.__func__
        if inspect.isclass(bound_to):
            # A classmethod, bound to the class (even when accessed through an instance).
            defining_class = _find_defining_class(bound_to, underlying_function)
            return MethodKind.CLASS, defining_class, bound_to
        defining_class = _find_defining_class(type(bound_to), underlying_function)
        return MethodKind.INSTANCE, defining_class, bound_to

    # Unbound: a plain function, a staticmethod, or a method read off the class.
    qualified_name = getattr(func, "__qualname__", "")
    # Anything before the last "<locals>" is an enclosing function; only what
    # comes after it can be followed as attribute lookups.
    path_after_locals = qualified_name.split(".<locals>.")[-1].split(".")
    if len(path_after_locals) == 1:
        return MethodKind.FUNCTION, None, None

    owner = _find_class_by_qualname(func)
    if owner is None:
        return MethodKind.UNKNOWN, None, None

    raw_attribute = inspect.getattr_static(owner, func.__name__, None)
    if isinstance(raw_attribute, staticmethod):
        return MethodKind.STATIC, owner, None
    if isinstance(raw_attribute, classmethod):
        return MethodKind.CLASS, owner, None
    return MethodKind.INSTANCE, owner, None

def _find_class_by_qualname(func: Callable[..., Any]) -> type | None:
    """
    Follow a function's __qualname__ from its module to the class that contains it.

    "Outer.Inner.method" in module "app.users" is resolved as
    app.users.Outer.Inner. Returns None if the module isn't loaded, any step is
    missing, the name passes through a function ("<locals>"), or the final
    object isn't a class.
    """
    qualified_name = getattr(func, "__qualname__", "")
    if "<locals>" in qualified_name:
        return None
    module = sys.modules.get(getattr(func, "__module__", None) or "")
    if module is None:
        return None

    current_object: Any = module
    for attribute_name in qualified_name.split(".")[:-1]:
        current_object = getattr(current_object, attribute_name, None)
        if current_object is None:
            return None
    return current_object if inspect.isclass(current_object) else None

def _find_defining_class(start_class: type, function: Callable[..., Any]) -> type | None:
    """
    Walk `start_class`'s method resolution order to find the class whose own
    namespace holds `function`.

    This matters for inherited methods: calling `Admin().save` produces a
    method bound to an Admin instance, but if `save` is defined on `User`,
    `User` is the owner. Methods stored under a different name (aliases)
    are found by scanning each class's attributes for the same function.
    """
    def unwrap_descriptor(attribute: Any) -> Any:
        """Return the plain function inside a staticmethod/classmethod wrapper."""
        # Checked by type name so `attribute` stays typed as Any; isinstance would narrow
        # it to staticmethod[..., Unknown], which strict type checkers then flag.
        if type(attribute) in (staticmethod, classmethod):
            return attribute.__func__
        return attribute

    for candidate_class in start_class.__mro__:
        namespace = vars(candidate_class)
        by_name = namespace.get(function.__name__)
        if by_name is not None and unwrap_descriptor(by_name) is function:
            return candidate_class
        if any(unwrap_descriptor(attribute) is function for attribute in namespace.values()):
            return candidate_class
    return None

def _resolve_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """
    Return the callable's type hints with string annotations evaluated.

    `include_extras=True` keeps Annotated wrappers, which typing.get_type_hints
    would otherwise strip. If a hint can't be resolved (for example, it refers
    to a name that isn't importable), fall back to the raw, unresolved annotations
    rather than failing the whole inspection.
    """
    target = inspect.unwrap(func)
    if inspect.isclass(target):
        target = target.__init__
    try:
        return typing.get_type_hints(target, include_extras=True)
    except Exception:
        return dict(getattr(target, "__annotations__", {}))
