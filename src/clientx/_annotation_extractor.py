from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from inspect import Signature
from types import MappingProxyType
from typing import Annotated, Any, TypeAliasType, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import ComputedFieldInfo, FieldInfo

from clientx._annotations import Part
from clientx.exceptions import MisplacedHelperError

# Enough for any real chain of aliases, and a stop for cyclic ones such as `type A = B` with `type B = A`.
_MAX_ALIAS_DEPTH = 100


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


def _nested_part(annotation: Any, expanded: frozenset[TypeAliasType] = frozenset()) -> Part | None:
    """Return a helper nested anywhere inside ``annotation``: in a union member, a type argument, or an alias.

    Each ``type`` alias is expanded at most once per path, so a recursive alias such as
    ``type Json = list[Json] | str`` doesn't loop.
    """
    for arg in get_args(annotation):
        alias = arg if isinstance(arg, TypeAliasType) else get_origin(arg)
        if isinstance(alias, TypeAliasType):
            if alias in expanded:
                continue
            expanded |= {alias}
            arg = _unwrap_type_alias(arg)
        if get_origin(arg) is Annotated and (part := _first_part(get_args(arg)[1:])) is not None:
            return part
        if (part := _nested_part(arg, expanded)) is not None:
            return part
    return None


def _first_part(metadata: Iterable[Any]) -> Part | None:
    return next((item for item in metadata if isinstance(item, Part)), None)


def _check_helpers(name: str, info: AnnotationInfo) -> AnnotationInfo:
    """Return ``info``, or raise ``MisplacedHelperError`` if a helper is nested or there's more than one.

    ``info`` is what the extractor read: the type left after the outermost ``Annotated``
    layers and ``type`` aliases are removed, and their metadata. ClientX only reads a
    helper from that metadata, so a helper anywhere inside the type would be ignored.
    """
    parts = [item for item in info.metadata if isinstance(item, Part)]
    if len(parts) > 1:
        helpers = ", ".join(f"{type(part).__name__}()" for part in parts)
        raise MisplacedHelperError(name, info.annotation, f"{name!r} has more than one helper: {helpers}")
    if (nested := _nested_part(info.annotation)) is not None:
        helper = type(nested).__name__
        problem = (
            f"{name!r} has {helper}() nested inside another type, where ClientX doesn't read it: {info.annotation!r}"
        )
        raise MisplacedHelperError(name, info.annotation, problem)
    return info


@dataclass(frozen=True)
class AnnotationInfo:
    """Normalized view of a type annotation and any Annotated metadata.

    Args:
        annotation: The underlying annotation, without the ``Annotated`` metadata.
        metadata: Metadata items attached via typing.Annotated.
    """

    annotation: Any = None
    metadata: list[Any] = field(default_factory=list[Any])

    @property
    def part(self) -> Part:
        """The first ``Part`` (or helper such as ``Query``) in the metadata, or an empty ``Part``."""
        return next((m for m in self.metadata if isinstance(m, Part)), Part())


@dataclass(frozen=True)
class NamedAnnotation:
    """A named annotation context pairing a name with its AnnotationInfo.

    Args:
        name: Field or parameter name used in error messages.
        info: Normalized annotation information for validation.
    """

    name: str
    info: AnnotationInfo

    @property
    def part(self) -> Part:
        """The first ``Part`` in the annotation's metadata, or an empty ``Part``."""
        return self.info.part


class AnnotationExtractor:
    """Build AnnotationInfo objects from typing and pydantic structures."""

    @staticmethod
    def from_field_annotation(annotation: Any) -> AnnotationInfo:
        """Parse a raw type annotation into AnnotationInfo.

        Args:
            annotation: The type annotation to parse.

        Returns:
            The normalized AnnotationInfo for the annotation. ``type`` aliases are
            expanded, and metadata from nested ``Annotated`` comes first, the way
            Python flattens ``Annotated[Annotated[T, inner], outer]``.
        """
        annotation = _unwrap_type_alias(annotation)
        if get_origin(annotation) is not Annotated:
            return AnnotationInfo(annotation=annotation)

        base, *metadata = get_args(annotation)
        # The base can itself be a `type` alias of an Annotated type.
        inner = AnnotationExtractor.from_field_annotation(base)
        return AnnotationInfo(annotation=inner.annotation, metadata=[*inner.metadata, *metadata])

    @staticmethod
    def from_field_info(field_info: FieldInfo | ComputedFieldInfo) -> AnnotationInfo:
        """Parse a pydantic FieldInfo / ComputedFieldInfo into AnnotationInfo.

        Args:
            field_info: Pydantic FieldInfo or ComputedFieldInfo to normalize.

        Returns:
            The normalized AnnotationInfo for the field.
        """
        if isinstance(field_info, ComputedFieldInfo):
            # For computed fields, the annotation lives in return_type.
            return AnnotationExtractor.from_field_annotation(field_info.return_type)

        # Runtime guard for untyped callers; the annotation already rules this out for type checkers.
        if not isinstance(field_info, FieldInfo):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"Expected FieldInfo or ComputedFieldInfo, got {type(field_info).__name__}")
        # Pydantic splits a field's own Annotated into annotation and metadata, but keeps a `type`
        # alias as the annotation, so the alias's metadata has to be read from it.
        inner = AnnotationExtractor.from_field_annotation(field_info.annotation)
        return AnnotationInfo(annotation=inner.annotation, metadata=[*inner.metadata, *field_info.metadata])

    @staticmethod
    def from_signature(signature: Signature) -> dict[str, AnnotationInfo]:
        """Map parameter names to AnnotationInfo extracted from a signature.

        Args:
            signature: The callable signature to inspect.

        Returns:
            A mapping of parameter name to AnnotationInfo.
        """
        return {
            name: _check_helpers(name, AnnotationExtractor.from_field_annotation(param.annotation))
            for name, param in signature.parameters.items()
        }

    @staticmethod
    def from_base_model(model: type[BaseModel] | BaseModel) -> dict[str, AnnotationInfo]:
        """Map model field names to AnnotationInfo (includes computed fields).

        Args:
            model: The BaseModel class or instance to inspect.

        Returns:
            A mapping of field names, aliases, and serialization aliases to
            AnnotationInfo for all fields.
        """
        model_type = model if isinstance(model, type) else type(model)
        fields = model_type.model_fields | model_type.model_computed_fields
        result: dict[str, AnnotationInfo] = {}
        for name, info in fields.items():
            annotation = _check_helpers(f"{model_type.__name__}.{name}", AnnotationExtractor.from_field_info(info))
            result[name] = annotation
            # A model dumped by alias uses the serialization alias, which can differ from the alias.
            serialization_alias = info.serialization_alias if isinstance(info, FieldInfo) else None
            for alias in (info.alias, serialization_alias):
                if alias:
                    result[alias] = annotation

        return result


class NamedAnnotationExtractor:
    """Build NamedAnnotation objects (attaches names for richer errors)."""

    @staticmethod
    def from_signature(signature: Signature) -> dict[str, NamedAnnotation]:
        """Map parameter names to NamedAnnotation objects from a signature.

        Args:
            signature: The callable signature to inspect.

        Returns:
            A mapping of parameter name to NamedAnnotation.
        """
        annotations = AnnotationExtractor.from_signature(signature)
        return {name: NamedAnnotation(name=name, info=info) for name, info in annotations.items()}

    @staticmethod
    def from_base_model(model: type[BaseModel] | BaseModel) -> dict[str, NamedAnnotation]:
        """Map model field names to NamedAnnotation objects (includes computed fields).

        Args:
            model: The BaseModel class or instance to inspect.

        Returns:
            A mapping of field name to NamedAnnotation for all fields.
        """
        annotations = AnnotationExtractor.from_base_model(model)
        return {name: NamedAnnotation(name=name, info=info) for name, info in annotations.items()}


@lru_cache(maxsize=512)
def model_annotations(model_type: type[BaseModel]) -> Mapping[str, NamedAnnotation]:
    """Return the field annotations of ``model_type``, analysed once per model class.

    The result depends only on the class, so it's cached, and read-only because it's
    shared. The cache is bounded, so models created on the fly can't grow it forever.
    ``MisplacedHelperError`` isn't cached: a model with a misplaced helper raises it
    every time.
    """
    return MappingProxyType(NamedAnnotationExtractor.from_base_model(model_type))
