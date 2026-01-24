import inspect
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Sequence, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from clientx.call_context import CallContext


class ReqPart(StrEnum):
    """Field enum for mapping fields into request payload sections."""

    PARAMS = "params"
    FILES = "files"
    DATA = "data"
    JSON = "json"
    HEADERS = "headers"


@dataclass
class ArgumentCursor:
    """Cursor over bound call arguments.

    This cursor provides a safe, non-mutating interface for consuming
    bound call arguments during request construction. It copies
    ``inspect.BoundArguments.arguments`` once and allows staged,
    single-consumption access to arguments while tracking what has
    already been consumed.

    Attributes:
        bound: The original ``inspect.BoundArguments`` produced by
            binding a callable's signature.
        consumed: Mapping of argument names to values that have been
            consumed.
        bound_copy: Mutable copy of ``bound.arguments`` used for
            consumption.
    """

    bound: inspect.BoundArguments
    consumed: dict[str, Any] = field(default_factory=dict)
    bound_copy: dict[str, Any] = field(init=False)

    def __post_init__(self):
        """Initialize the mutable copy of bound arguments."""
        self.bound_copy = dict(self.bound.arguments)

    def consume(self, name: str) -> Any:
        """Consume a required argument by name.

        Args:
            name: Argument name to consume.

        Returns:
            The argument value.

        Raises:
            KeyError: If the argument is missing or already consumed.
        """
        if name in self.consumed:
            raise KeyError(f"Argument '{name}' already consumed")
        try:
            value = self.bound_copy.pop(name)
        except KeyError as e:
            raise KeyError(f"Argument '{name}' not available (missing)") from e
        self.consumed[name] = value
        return value

    def consume_optional(self, name: str, default: Any = None) -> Any:
        """Consume an optional argument if present.

        Args:
            name: Argument name to consume.
            default: Value to return if the argument is missing.

        Returns:
            The argument value if present, otherwise the default.
        """
        if name in self.consumed:
            return self.consumed[name]
        if name not in self.bound_copy:
            return default
        value = self.bound_copy.pop(name)
        self.consumed[name] = value
        return value

    def is_consumed(self, name: str) -> bool:
        """Check whether an argument has been consumed.

        Args:
            name: Argument name to check.

        Returns:
            True if the argument has been consumed, otherwise False.
        """
        return name in self.consumed

    def leftovers(self) -> dict[str, Any]:
        """Return remaining unconsumed arguments.

        Returns:
            Mapping of remaining argument names to values.
        """
        return dict(self.bound_copy)

    def consumed_items(self) -> dict[str, Any]:
        """Return consumed arguments.

        Returns:
            Mapping of consumed argument names to values.
        """
        return dict(self.consumed)

    def assert_empty(self) -> None:
        """Assert that all arguments were consumed.

        Raises:
            TypeError: If any unconsumed arguments remain.
        """
        if self.bound_copy:
            raise TypeError(f"Unhandled arguments: {', '.join(self.bound_copy)}")


@dataclass
class RequestFactory:
    """Construct HTTP request parts from a call context."""

    strict: bool = True
    warn_on_conflict: bool = False

    def __call__(self, call_ctx: CallContext) -> dict[str, Any]:
        """Build a request for a call context.

        Args:
            call_ctx: Call metadata and bound arguments.

        Returns:
            Request parts including the rendered path.
        """
        cursor = ArgumentCursor(call_ctx.bound)

        # 1) drop self from request materialization
        cursor.consume_optional("self")
        rendered_path = self.render_path(call_ctx, cursor)

        request_parts = self.extract_request_parts(call_ctx, cursor)
        request = self.merge_request_parts(request_parts)

        return {"path": rendered_path, **request}

    def render_path(self, call: CallContext, cursor: ArgumentCursor) -> str:
        """Render the endpoint path using bound arguments.

        Args:
            call: Call metadata describing the endpoint.
            cursor: Cursor over bound arguments for consumption.

        Returns:
            The formatted request path.
        """
        path_parameters = call.path.parameters
        values = {name: cursor.consume(name) for name in path_parameters}

        return call.path.format(values)

    def extract_request_parts(
        self,
        call: CallContext,
        cursor: ArgumentCursor,
    ) -> list[dict[str, Any]]:
        """Extract HTTP request parts from remaining arguments.

        Args:
            call: Call metadata describing the endpoint.
            cursor: Cursor over bound arguments for consumption.

        Returns:
            List of request part mappings suitable for httpx.request(**kwargs).
        """
        parts = []

        parameters = call.function_parameters
        model_processor = ModelRequestParts()
        field_processor = FieldRequestParts()

        for name, param in parameters.items():
            if name in cursor.consumed:  # already consumed or never bound
                continue

            if model_processor.is_base_model(param.annotation):
                model = cast(BaseModel, cursor.consume(name))
                part = model_processor(model)
                parts.append(part)

            elif field_processor.is_annotated(param.annotation):
                if part := field_processor(name, param.annotation, cursor):
                    parts.append(part)

        return parts

    def merge_request_parts(self, request_parts: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge request part mappings into a single request payload.

        Args:
            request_parts: Request part mappings to merge.

        Returns:
            Combined request mapping. Later parts win on conflicts. When both values
            are dicts, they are shallow-merged and later parts win on shared keys.
        """
        merged: dict[str, Any] = {}

        for part in request_parts:
            for key, value in part.items():
                if key not in merged:
                    merged[key] = value
                    continue
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    self._warn_on_conflict(key, merged[key], value)
                    merged[key].update(value)
                    continue

                self._warn_on_full_overlap(key, merged[key], value)
                merged[key] = value

        return merged

    def _warn_on_conflict(self, request_part: str, existing: dict[str, Any], incoming: dict[str, Any]) -> None:
        """Warn when request part dictionaries share keys.

        Args:
            request_part: Request part key being merged.
            existing: Existing request part mapping.
            incoming: Incoming request part mapping.
        """
        if self.warn_on_conflict and (overlap := set(existing).intersection(incoming)):
            warnings.warn(
                f"Request parts share keys for '{request_part}': {', '.join(sorted(overlap))}",
                stacklevel=2,
            )

    def _warn_on_full_overlap(self, request_part: str, existing: Any, incoming: Any) -> None:
        """Warn when a request part is fully replaced.

        Args:
            request_part: Request part key being overwritten.
            existing: Existing request part value.
            incoming: Incoming request part value.
        """
        if self.warn_on_conflict:
            warnings.warn(
                f"Request part '{request_part}' fully overwritten",
                stacklevel=2,
            )


def get_request_field(meta: Sequence[Any]) -> ReqPart | None:
    """Return the first RequestField marker from a metadata sequence, if any.

    Args:
        meta: Annotation metadata items to search.

    Returns:
        The first RequestField marker, if present.
    """
    return next((m for m in meta if isinstance(m, ReqPart)), None)


class FieldRequestParts:
    def __call__(self, field_name: str, annotation: Any, cursor: ArgumentCursor) -> dict[str, Any] | None:
        """Build request parts for an Annotated argument.

        Args:
            field_name: Name of the bound argument.
            annotation: Annotation carrying a RequestField marker.
            cursor: Cursor over bound arguments for consumption.

        Returns:
            Request part mapping, or None if no RequestField is present.
        """
        part = defaultdict(dict)

        if not (field := self.request_field_from_annotation(annotation)):
            return None

        value = cursor.consume(field_name)
        part[field].update({field_name: value})

        return dict(part)

    def is_annotated(self, annotation: Any) -> bool:
        """Return whether an annotation is typing.Annotated."""
        return get_origin(annotation) is Annotated

    def request_field_from_annotation(self, annotation: Any) -> ReqPart | None:
        """Return the RequestField marker from an Annotated annotation, if present."""
        _, *meta = get_args(annotation)
        return get_request_field(meta)


class ModelRequestParts:
    def __call__(self, model: BaseModel) -> dict[str, Any]:
        """Build request parts from a Pydantic model.

        Args:
            model: Model instance to extract request fields from.

        Returns:
            Request part mapping derived from the model.
        """
        part_map = self.get_request_field_map(model)
        dump = model.model_dump()

        return self.build_request_parts(dump, part_map)

    def build_request_parts(self, dump: dict[str, Any], part_map: dict[ReqPart, set[str]]) -> dict[str, dict[str, Any]]:
        """Build request parts based on a dump and request field mapping.

        Args:
            dump: Model dump of field values.
            part_map: Mapping of request parts to field/alias pairs.

        Returns:
            Request part mapping grouped by request section.
        """
        request_parts = defaultdict(dict)

        for request_part, fields in part_map.items():
            for field_keys in fields:
                # field = (model_field, alias)
                # Prefer the field name when present, otherwise fall back to the alias.
                field_key: str = next(f for f in field_keys if f in dump)

                # If a field name matches a request payload key (json/data/file/params/headers),
                # treat its value as the whole payload for that request part.
                if field_key == request_part:
                    request_parts[request_part] = dump.pop(field_key)

                if field_key in dump:
                    request_parts[request_part][field_key] = dump.pop(field_key)

        # Promote explicit request-part keys (json/data/file/params)
        # treat its value as the whole payload for that request part.
        for part in ReqPart:
            if part in dump:
                request_parts[part] = dump.pop(part)

        # Any remaining fields default to the JSON request body.
        if dump:
            request_parts[ReqPart.JSON] = dump

        return dict(request_parts)

    def is_base_model(self, annotation: Any) -> bool:
        """Return whether an annotation resolves to a BaseModel subtype.

        Args:
            annotation: Annotation to inspect.

        Returns:
            True if the annotation resolves to a BaseModel subtype.
        """
        origin = get_origin(annotation) or annotation
        return isinstance(origin, type) and issubclass(origin, BaseModel)

    def get_request_field_map(self, model: BaseModel) -> dict[ReqPart, set[str]]:
        """Build a mapping of request parts to model field and alias pairs.

        Args:
            model: Model instance to inspect for request field metadata.

        Returns:
            Mapping of request parts to field and alias pairs.

        Example:
            >>> class Payload(BaseModel):
            ...     token: Annotated[str, RequestField.HEADERS]
            ...     data: Annotated[str, RequestField.JSON] = Field(alias="payload")
            >>> ModelRequestParts().get_request_field_map(
            ...     Payload(token="t", payload="d")
            ... )
            {<RequestField.HEADERS: 'headers'>: {('token', None)},
             <RequestField.JSON: 'json'>: {('data', 'payload')}}
        """
        field_reference = defaultdict(set)
        model_fields = type(model).model_fields | type(model).model_computed_fields

        for name, info in model_fields.items():
            # FieldInfo
            if isinstance(info, FieldInfo):
                if field := get_request_field(info.metadata):
                    field_reference[field].add((name, info.alias))
                continue

            # ComputedFieldInfo
            if get_origin(info.return_type) is Annotated:
                return_args = get_args(info.return_type)
                if field := get_request_field(return_args):
                    field_reference[field].add((name, info.alias))

        return dict(field_reference)
