"""
Result objects returned by describe_signature.

    SignatureInfo   Describes a whole callable: its parameters, return type, which class
                    (if any) owns it, and helpers for looking up parameters and binding
                    call arguments.
    ParameterInfo   Describes one parameter: its kind, default, type hint, and any
                    metadata attached with typing.Annotated.
    ReturnInfo      Describes the return type and its Annotated metadata.
    MethodKind      How a callable relates to a class (function, instance method, ...).

These are plain frozen dataclasses with no dependency on how they were built, so they
can be imported anywhere (type hints, tests, serializers) without pulling in the
inspection logic.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from clientx._compiler.type_hints import NO_VALUE, describe_type, is_optional_type

MetadataType = TypeVar("MetadataType")

# The enum behind inspect.Parameter.kind (POSITIONAL_ONLY, KEYWORD_ONLY, ...).
# inspect doesn't export it under a public name, so alias it here once.
ParameterKind = inspect._ParameterKind  # pyright: ignore[reportPrivateUsage]


# --------------------------------------------------------------------------- #
# Result objects
# --------------------------------------------------------------------------- #
class MethodKind(str, Enum):
    """
    How a callable relates to a class.

        FUNCTION      Not defined on a class: a module-level or nested function.
        INSTANCE      A regular method that receives `self`.
        CLASS         A @classmethod that receives `cls`.
        STATIC        A @staticmethod that receives neither.
        CONSTRUCTOR   A class itself, inspected through its __init__.
        UNKNOWN       The qualified name says it lives on a class, but the class
                      couldn't be found, typically because it was defined inside
                      a function and isn't reachable from its module.
    """

    FUNCTION = "function"
    INSTANCE = "instance"
    CLASS = "class"
    STATIC = "static"
    CONSTRUCTOR = "constructor"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParameterInfo:
    """
    Everything known about a single parameter of a callable.

    Attributes:
        name:         The parameter's name as written in the function definition.
        position:     Zero-based index of the parameter in the signature.
        kind:         How the parameter can be passed: positional-only, positional-or-keyword,
                      *args, keyword-only, or **kwargs.
        annotation:   The type hint exactly as written, including any Annotated wrapper,
                      e.g. Annotated[int, Range(1, 10)]. NO_VALUE if there is no annotation.
        base_type:    The type hint with Annotated stripped off, e.g. int.
        metadata:     The extra objects attached through Annotated, e.g. (Range(1, 10),).
        default:      The default value, or NO_VALUE if the parameter has none.
    """

    name: str
    position: int
    kind: ParameterKind
    annotation: Any
    base_type: Any
    metadata: tuple[Any, ...]
    default: Any = NO_VALUE

    # --- descriptive properties ---
    @property
    def has_default(self) -> bool:
        """True if the parameter declares a default value."""
        return self.default is not NO_VALUE

    @property
    def is_required(self) -> bool:
        """True if a caller must supply this argument (no default, and not *args/**kwargs)."""
        return not self.has_default and not self.is_variadic

    @property
    def has_annotation(self) -> bool:
        """True if the parameter has a type hint."""
        return self.annotation is not NO_VALUE

    @property
    def is_optional(self) -> bool:
        """True if the type hint allows None, e.g. `int | None`. Unrelated to having a default."""
        return is_optional_type(self.base_type)

    @property
    def is_variadic(self) -> bool:
        """True for *args and **kwargs parameters."""
        return self.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)

    @property
    def can_pass_positionally(self) -> bool:
        """True if the argument can be passed by position (excludes *args itself)."""
        return self.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    @property
    def can_pass_by_keyword(self) -> bool:
        """True if the argument can be passed as name=value (excludes **kwargs itself)."""
        return self.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )

    # --- metadata helpers ---
    def get_metadata(self, metadata_class: type[MetadataType]) -> list[MetadataType]:
        """Return every metadata object that is an instance of `metadata_class`, in order."""
        return [item for item in self.metadata if isinstance(item, metadata_class)]

    def first_metadata(
        self, metadata_class: type[MetadataType], default: MetadataType | None = None
    ) -> MetadataType | None:
        """Return the first metadata object of `metadata_class`, or `default` if there is none."""
        return next(iter(self.get_metadata(metadata_class)), default)

    def has_metadata(self, metadata_class: type) -> bool:
        """True if any metadata object is an instance of `metadata_class`."""
        return any(isinstance(item, metadata_class) for item in self.metadata)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly description of the parameter."""
        return {
            "name": self.name,
            "position": self.position,
            "kind": self.kind.name,
            "type": describe_type(self.base_type),
            "required": self.is_required,
            "default": repr(self.default) if self.has_default else None,
            "metadata": [repr(item) for item in self.metadata],
        }


@dataclass(frozen=True)
class ReturnInfo:
    """
    Everything known about a callable's return type.

    Attributes:
        annotation:  The return type hint exactly as written, including Annotated.
        base_type:   The return type with Annotated stripped off.
        metadata:    The extra objects attached through Annotated.
    """

    annotation: Any
    base_type: Any
    metadata: tuple[Any, ...]

    def get_metadata(self, metadata_class: type[MetadataType]) -> list[MetadataType]:
        """Return every metadata object that is an instance of `metadata_class`, in order."""
        return [item for item in self.metadata if isinstance(item, metadata_class)]


@dataclass(frozen=True)
class SignatureInfo:
    """
    A full description of a callable's signature, with helpers for querying it.

    Look up parameters by name or position (`info["email"]`, `info[0]`), iterate over
    them in order, filter them (`.required_parameters`, `.params_with(Marker)`), and
    map a set of call arguments to parameter names (`.bind`).

    Attributes:
        func:        The callable that was inspected.
        name:        The callable's __name__.
        qualname:    The callable's __qualname__, which includes any enclosing class.
        module:      The module the callable was defined in.
        doc:         The cleaned-up docstring, or None.
        is_async:    True if the callable (after unwrapping decorators) is a coroutine function.
        method_kind: How the callable relates to a class (see MethodKind).
        owner:       The class that defines the callable, or None for plain functions and
                     for methods whose class couldn't be found. For inherited methods this
                     is the class where the method is actually defined, not the subclass
                     it was accessed through.
        bound_to:    For bound methods, the object passed as the first argument: the
                     instance for instance methods, the class for class methods.
                     None when the callable isn't bound.
        parameters:  One ParameterInfo per parameter, in definition order. For bound
                     methods, `self` / `cls` is already excluded.
        returns:     A ReturnInfo describing the return type.
        signature:   The underlying inspect.Signature, used for argument binding.
    """

    func: Callable[..., Any]
    name: str
    qualname: str
    module: str | None
    doc: str | None
    is_async: bool
    method_kind: MethodKind
    owner: type | None
    bound_to: Any
    parameters: tuple[ParameterInfo, ...]
    returns: ReturnInfo
    signature: inspect.Signature = field(repr=False)

    # --- container behaviour ---
    def __iter__(self) -> Iterator[ParameterInfo]:
        return iter(self.parameters)

    def __len__(self) -> int:
        return len(self.parameters)

    def __contains__(self, parameter_name: str) -> bool:
        return any(parameter.name == parameter_name for parameter in self.parameters)

    def __getitem__(self, name_or_position: str | int) -> ParameterInfo:
        """Look up a parameter by name (str) or by zero-based position (int)."""
        if isinstance(name_or_position, int):
            return self.parameters[name_or_position]
        for parameter in self.parameters:
            if parameter.name == name_or_position:
                return parameter
        raise KeyError(name_or_position)

    # --- ownership ---
    @property
    def is_method(self) -> bool:
        """True for instance, class, and static methods, including ones whose owner wasn't found."""
        return self.method_kind in (
            MethodKind.INSTANCE,
            MethodKind.CLASS,
            MethodKind.STATIC,
            MethodKind.UNKNOWN,
        )

    @property
    def is_bound(self) -> bool:
        """True if the callable is a bound method, so `self` / `cls` is supplied automatically."""
        return self.bound_to is not None

    @property
    def owner_name(self) -> str | None:
        """The owning class's qualified name, e.g. 'UserService', or None if there's no owner."""
        return self.owner.__qualname__ if self.owner is not None else None

    # --- filtered views ---
    @property
    def required_parameters(self) -> list[ParameterInfo]:
        """Parameters the caller must supply."""
        return [parameter for parameter in self.parameters if parameter.is_required]

    @property
    def parameters_with_defaults(self) -> list[ParameterInfo]:
        """Parameters that can be omitted because they have a default."""
        return [parameter for parameter in self.parameters if parameter.has_default]

    @property
    def positional_parameters(self) -> list[ParameterInfo]:
        """Parameters that can be passed by position (positional-only or positional-or-keyword)."""
        return [parameter for parameter in self.parameters if parameter.can_pass_positionally]

    @property
    def keyword_only_parameters(self) -> list[ParameterInfo]:
        """Parameters that must be passed as name=value (declared after * or *args)."""
        return [parameter for parameter in self.parameters if parameter.kind is inspect.Parameter.KEYWORD_ONLY]

    @property
    def accepts_extra_positional(self) -> bool:
        """True if the callable declares *args."""
        return any(parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in self.parameters)

    @property
    def accepts_extra_keywords(self) -> bool:
        """True if the callable declares **kwargs."""
        return any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in self.parameters)

    def params_with(self, metadata_class: type) -> list[ParameterInfo]:
        """
        Return every parameter tagged with an Annotated metadata object of `metadata_class`.

        Useful for metadata-driven behaviour, e.g. finding all parameters marked
        Sensitive so their values can be redacted from logs.
        """
        return [parameter for parameter in self.parameters if parameter.has_metadata(metadata_class)]

    # --- call helpers ---
    def bind(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Map call arguments to parameter names, filling in defaults for anything omitted.

        *args values are collected into a tuple and **kwargs values into a dict, just
        as Python would do when calling the function.

        Raises:
            TypeError: if the arguments don't fit the signature (missing, extra,
                       or duplicated arguments).
        """
        bound_arguments = self.signature.bind(*args, **kwargs)
        bound_arguments.apply_defaults()
        return dict(bound_arguments.arguments)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly description of the whole signature."""
        return {
            "name": self.qualname,
            "module": self.module,
            "async": self.is_async,
            "method_kind": self.method_kind.value,
            "owner": self.owner_name,
            "bound": self.is_bound,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "returns": describe_type(self.returns.base_type),
        }
