from __future__ import annotations

import inspect
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from clientx.annotations import DumpOptions, NamedAnnotation, NamedAnnotationExtractor, RequestSection
from clientx.call_context import CallContext
from clientx.exceptions import UnconsumableArgumentError

type PartMap = dict[RequestSection, set[tuple[str, None]]]


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


@dataclass(frozen=True)
class RequestFactory:
    """Construct HTTP request parts from a call context."""

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

            Parameters are converted into request parts using one of three strategies:
            - Parameter name matches a RequestSection (e.g., ``json`` or ``params``).
            - Parameter is annotated with a RequestSection via ``Annotated`` metadata.
            - Parameter value is a Pydantic model, which is expanded by ModelExtractor.
        """
        parts = []
        annotation_map = NamedAnnotationExtractor.from_signature(call.function_signature)
        model_extractor = ModelExtractor()

        for field_name, annotation in annotation_map.items():
            # already consumed (e.g., self or path parameters)
            if field_name in cursor.consumed:
                continue

            value = cursor.consume(field_name)

            if key := RequestSection.get(field_name) or annotation.request_section:
                parts.append(
                    {key: value.model_dump(**annotation.dump_options.kwargs) if isinstance(value, BaseModel) else value}
                )
                continue

            elif isinstance(value, BaseModel):
                parts.append(model_extractor(model=value, dump_options=annotation.dump_options))
                continue

            raise UnconsumableArgumentError(field=field_name, annotation=annotation, value=value)

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


@dataclass(frozen=True)
class ModelExtractor:
    def __call__(self, model: BaseModel, dump_options: DumpOptions) -> dict[str, Any]:
        """Build request parts from a Pydantic model.

        Args:
            model: Model instance to extract request fields from.
            dump_options: Serialization options passed to ``model_dump``.

        Returns:
            Request part mapping derived from the model.
        """
        annotation_map = NamedAnnotationExtractor.from_base_model(model)
        dump = model.model_dump(**dump_options.kwargs)
        return self.build_request_arguments(dump, annotation_map)

    def build_request_arguments(
        self, dump: dict[str, Any], annotation_map: dict[str, NamedAnnotation]
    ) -> dict[str, dict[str, Any]]:
        """Build request parts based on a model dump and annotation mapping.

        Args:
            dump: Model dump to map into request parts. This dict is mutated as fields are assigned.
            annotation_map: Mapping of model field names (and aliases) to annotations.

        Returns:
            Request part mapping grouped by request section. Fields marked with a
            RequestSection are merged into that section and are expected to be
            mapping values. Remaining fields default to the JSON section.
        """
        request = defaultdict(dict)

        for key in list(dump):
            annotation = annotation_map[key]
            if section := annotation.info.request_section:
                request[section].update(dump.pop(key))

        if dump:
            request[RequestSection.JSON].update(**dump)

        return request
