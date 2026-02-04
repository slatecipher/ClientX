from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from inspect import Signature
from typing import Annotated, Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from pydantic.fields import ComputedFieldInfo, FieldInfo


class DumpOptions(BaseModel):
    """Options for controlling Pydantic serialization output.

    For more context on each option, see:
        `https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_dump`

    Attributes:
        mode: Controls how values are serialized. Use "json" for JSON-serializable types only, or
            "python" to allow non-JSON-serializable Python objects. Defaults to "python".
        include: Fields to include in the output (Pydantic include/exclude spec). Defaults to None.
        exclude: Fields to exclude from the output (Pydantic include/exclude spec). Defaults to None.
        context: Additional context passed to the serializer. Defaults to None.
        by_alias: Whether to use field aliases as dictionary keys. Defaults to None.
        exclude_unset: Whether to exclude fields that were not explicitly set. Defaults to False.
        exclude_defaults: Whether to exclude fields set to their default value. Defaults to False.
        exclude_none: Whether to exclude fields with a value of None. Defaults to False.
        exclude_computed_fields: Whether to exclude computed fields. Defaults to False.
        round_trip: Whether dumped values should be valid inputs for non-idempotent types such as Json[T].
            Defaults to False.
        warnings: How to handle serialization errors. False/"none" ignores, True/"warn" logs, and
            "error" raises a PydanticSerializationError. Defaults to True.
        serialize_as_any: Whether to serialize fields with duck-typing serialization behavior. Defaults to False.
    """

    mode: Literal["json", "python"] | str = "python"
    include: Any = None
    exclude: Any = None
    context: dict[str, Any] | None = None
    by_alias: bool | None = None
    exclude_unset: bool = False
    exclude_defaults: bool = False
    exclude_none: bool = False
    exclude_computed_fields: bool = False
    round_trip: bool = False
    warnings: bool | Literal["none", "warn", "error"] = True
    serialize_as_any: bool = False

    @property
    def kwargs(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class RequestSection(StrEnum):
    """Field enum for mapping fields into request payload sections.

    The values correspond to keyword arguments used by HTTP client request APIs.
    """

    PARAMS = "params"
    FILES = "files"
    DATA = "data"
    JSON = "json"
    HEADERS = "headers"

    @classmethod
    def get(cls, value: str) -> RequestSection | None:
        """Return the matching enum member for a string, if present.

        Args:
            value: Candidate request section string.

        Returns:
            The matching RequestSection member, or None when the value is not a member.
        """
        return cls(value) if value in RequestSection else None


@dataclass(frozen=True)
class AnnotationInfo:
    """Normalized view of a type annotation and any Annotated metadata.

    Args:
        annotation: The underlying annotation to validate against.
        metadata: Metadata items attached via typing.Annotated.
    """

    annotation: Any = None
    metadata: list[Any] = field(default_factory=list)

    @property
    def request_section(self) -> RequestSection | None:
        """Return the first RequestSection marker from metadata, if present.

        Returns:
            The first RequestSection found in metadata, or None when not present.
        """
        return next((m for m in self.metadata if isinstance(m, RequestSection)), None)

    @property
    def dump_options(self) -> DumpOptions:
        """Return the first DumpOptions marker from metadata, if present.

        Returns:
            The first DumpOptions found in metadata, or a default DumpOptions instance when not present.
        """
        return next((d for d in self.metadata if isinstance(d, DumpOptions)), DumpOptions())

    def validate(self, value: Any) -> None:
        """Validate a value against this annotation.

        Args:
            value: Value to validate.

        Raises:
            ValidationError: Raised by Pydantic when validation fails.
        """
        TypeAdapter(self.annotation).validate_python(value)


@dataclass(frozen=True)
class NamedAnnotation:
    """A named annotation context pairing a name with its AnnotationInfo.

    Args:
        name: Field or parameter name used in error messages.
        info: Normalized annotation information for validation.
    """

    name: str
    info: AnnotationInfo

    def validate(self, value: Any) -> None:
        """Validate and raise an error that includes the field/parameter name.

        Args:
            value: Value to validate.

        Raises:
            ValueError: Raised when validation fails, wrapping the original ValidationError.
        """
        try:
            self.info.validate(value)
        except ValidationError as e:
            raise ValueError(f"{self.name!r}: {e}") from e

    @property
    def dump_options(self) -> DumpOptions:
        return self.info.dump_options

    @property
    def request_section(self) -> RequestSection | None:
        return self.info.request_section


class AnnotationExtractor:
    """Build AnnotationInfo objects from typing and pydantic structures."""

    @staticmethod
    def from_field_annotation(annotation: Any) -> AnnotationInfo:
        """Parse a raw type annotation into AnnotationInfo.

        Args:
            annotation: The type annotation to parse.

        Returns:
            The normalized AnnotationInfo for the annotation.
        """
        if get_origin(annotation) is not Annotated:
            return AnnotationInfo(annotation=annotation)

        base, *metadata = get_args(annotation)
        return AnnotationInfo(annotation=base, metadata=list(metadata))

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

        assert isinstance(field_info, FieldInfo)
        # FieldInfo.annotation is already the underlying type; metadata is separate.
        return AnnotationInfo(annotation=field_info.annotation, metadata=list(field_info.metadata))

    @staticmethod
    def from_signature(signature: Signature) -> dict[str, AnnotationInfo]:
        """Map parameter names to AnnotationInfo extracted from a signature.

        Args:
            signature: The callable signature to inspect.

        Returns:
            A mapping of parameter name to AnnotationInfo.
        """
        return {
            name: AnnotationExtractor.from_field_annotation(param.annotation)
            for name, param in signature.parameters.items()
        }

    @staticmethod
    def from_base_model(model: type[BaseModel] | BaseModel) -> dict[str, AnnotationInfo]:
        """Map model field names to AnnotationInfo (includes computed fields).

        Args:
            model: The BaseModel class or instance to inspect.

        Returns:
            A mapping of field name to AnnotationInfo for all fields.
        """
        model_type = model if isinstance(model, type) else type(model)
        fields = model_type.model_fields | model_type.model_computed_fields
        result = {}
        for name, info in fields.items():
            annotation = AnnotationExtractor.from_field_info(info)
            result[name] = annotation
            if info.alias:
                result[info.alias] = annotation

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
