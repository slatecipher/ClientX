from __future__ import annotations

import inspect
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from inspect import BoundArguments
from typing import Any, cast, get_args

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from clientx._annotation_extractor import NamedAnnotation, model_annotations
from clientx._annotations import DumpConfig
from clientx._client_types import RequestPartName
from clientx._endpoint_context import Endpoint
from clientx.exceptions import UnconsumableArgumentError

# Request parts that are flat name-value pairs, where a single value can be sent under a key.
_KEYED_PARTS: frozenset[RequestPartName] = frozenset({"params", "headers", "data"})

# A parameter named after a request part ("params", "json", ...) holds that whole part. Built from
# RequestPartName, so the names are defined once.
_PARTS_BY_NAME: dict[str, RequestPartName] = {name: name for name in get_args(RequestPartName.__value__)}

# How models are dumped unless a DumpConfig says otherwise: JSON-compatible values (ISO 8601 dates,
# strings for UUIDs and decimals) under each field's alias, which is usually the API's own name.
_DUMP_DEFAULTS: DumpConfig = {"mode": "json", "by_alias": True}


def dump_model(model: BaseModel, dump_config: DumpConfig) -> dict[str, Any]:
    """Dump a model for a request, with ``dump_config`` on top of ClientX's defaults.

    Args:
        model: Model instance to dump.
        dump_config: Serialization options. Each one overrides ClientX's default,
            ``mode="json"`` and ``by_alias=True``.

    Returns:
        The dumped model.
    """
    config: DumpConfig = {**_DUMP_DEFAULTS, **dump_config}
    return model.model_dump(**config)


def _sends_single_value(part: RequestPartName, key: str | None, value: object, *, whole_part: bool) -> bool:
    """Whether ``value`` is sent as one named value in ``part``, rather than merged into it.

    Query parameters, headers, and form fields are name-value pairs. A value with a ``key``
    is always one named value. Without a key, a mapping (or a value for a parameter named
    after the part) is the whole part, and anything else is one named value.
    """
    if part not in _KEYED_PARTS:
        return False
    return key is not None or not (whole_part or isinstance(value, Mapping))


def _default_name(name: str, part: RequestPartName) -> str:
    """The name a single value is sent under without a ``key``.

    It's the parameter or field name. For headers, underscores become hyphens, like
    FastAPI's ``Header()``: many proxies drop headers with underscores.
    """
    return name.replace("_", "-") if part == "headers" else name


def _clean_keyed_part(part: RequestPartName, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a ``params``, ``headers``, or ``data`` dict for httpx2.

    ``None`` values are left out, because httpx2 sends them as empty values, or rejects
    them as headers. Numbers and booleans in headers are written as JSON text (``2``,
    ``true``), because httpx2 only accepts strings there.
    """
    cleaned = {name: item for name, item in values.items() if item is not None}
    if part == "headers":
        return {
            name: json.dumps(item) if isinstance(item, bool | int | float) else item for name, item in cleaned.items()
        }
    return cleaned


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
    consumed: dict[str, Any] = field(default_factory=dict[str, Any])
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

    def is_consumed(self, name: str) -> bool:
        """Check whether an argument has been consumed.

        Args:
            name: Argument name to check.

        Returns:
            True if the argument has been consumed, otherwise False.
        """
        return name in self.consumed


@dataclass(frozen=True)
class RequestSpec:
    """A rendered endpoint call, split into routing and payload.

    Attributes:
        path: Rendered request path with template placeholders applied.
        parts: Merged request parts suitable for ``httpx2.Client.build_request``.
            Never contains ``method``, ``path``, or ``stream`` — those are passed
            to ``ClientX.send`` as named arguments.
    """

    path: str
    parts: dict[str, Any]


@dataclass(frozen=True)
class RequestFactory:
    """Construct HTTP request inputs from a bound endpoint invocation.

    Attributes:
        endpoint: Endpoint metadata and signature used to consume arguments.
    """

    endpoint: Endpoint

    def __call__(self, arguments: BoundArguments) -> RequestSpec:
        """Build a rendered path and merged request parts from bound arguments.

        Args:
            arguments: Bound endpoint arguments produced from signature binding.

        Returns:
            RequestSpec: The rendered path and the merged request parts.
        """
        cursor = ArgumentCursor(arguments)

        # The first parameter is the client or resource, whatever it's named.
        cursor.consume(self.endpoint.client_parameter)
        rendered_path = self.render_path(cursor)

        request_parts = self.extract_request_parts(cursor)

        return RequestSpec(path=rendered_path, parts=self.merge_request_parts(request_parts))

    def render_path(self, cursor: ArgumentCursor) -> str:
        """Render the endpoint path using bound arguments.

        Args:
            cursor: Cursor over bound arguments for consumption.

        Returns:
            str: Formatted request path with template parameters applied.

        Raises:
            KeyError: If a required path parameter has already been consumed or
                is missing from the bound arguments.
        """

        path_parameters = self.endpoint.path.parameters
        values = {name: cursor.consume(name) for name in path_parameters}

        return self.endpoint.path.format(values)

    def extract_request_parts(
        self,
        cursor: ArgumentCursor,
    ) -> list[dict[str, Any]]:
        """Extract HTTP request parts from remaining arguments.

        Args:
            cursor: Cursor over bound arguments for consumption.

        Returns:
            list[dict[str, Any]]: Request part mappings suitable for
                ``httpx2.request(**kwargs)``.

            Parameters are converted into request parts using one of three strategies:
            - Parameter name is a request part (for example ``json`` or ``params``).
            - Parameter is annotated with a ``Part``, such as ``Query()`` or ``Body()``, via ``Annotated``.
            - Parameter value is a Pydantic model, expanded by ``ModelExtractor``.

            In ``params``, ``headers``, and ``data``, a ``Part`` value that isn't a
            mapping is sent under its ``key``, or under the parameter name (with
            hyphens for headers). It's left out when it is ``None``, so optional
            query parameters, headers, and form fields can default to ``None``.
            ``merge_request_parts`` leaves out ``None`` values from mappings and models too.

        Raises:
            UnconsumableArgumentError: If a parameter cannot be mapped to a
                request part.
        """
        parts: list[dict[str, Any]] = []
        model_extractor = ModelExtractor()

        # Analysed once when the class was defined; the client parameter isn't in it.
        for field_name, annotation in self.endpoint.parameters.items():
            # Already consumed as a path parameter.
            if cursor.is_consumed(field_name):
                continue

            value = cursor.consume(field_name)

            marker = annotation.part

            named_part = _PARTS_BY_NAME.get(field_name)
            if part := named_part or marker.request_part:
                if isinstance(value, BaseModel):
                    payload = dump_model(value, marker.dump_config)
                elif _sends_single_value(part, marker.key, value, whole_part=named_part is not None):
                    if value is None:
                        # Leave it out: httpx2 sends None as an empty query or form value and rejects it as a header.
                        continue
                    # Like a model field in JSON mode: an Enum becomes its value, a datetime ISO 8601.
                    payload = {marker.key or _default_name(field_name, part): to_jsonable_python(value)}
                else:
                    payload = value

                parts.append({part: payload})
                continue

            elif isinstance(value, BaseModel):
                parts.append(model_extractor(model=value, dump_config=marker.dump_config))
                continue

            raise UnconsumableArgumentError(field=field_name, annotation=annotation, value=value)

        return parts

    def merge_request_parts(self, request_parts: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge request part mappings into a single request payload.

        Args:
            request_parts: Request part mappings to merge.

        Returns:
            Combined request mapping. Later parts win on conflicts, silently: that's
            the documented rule, so a parameter can override part of a whole-part
            argument such as ``headers``. When both values are dicts, they are
            shallow-merged and later parts win on shared keys.
            ``None`` values are left out of ``params``, ``headers``, and ``data``;
            ``json`` keeps them as ``null``. Numbers and booleans in headers become
            text. Dicts passed in are never changed.
        """
        merged: dict[str, Any] = {}

        for part in request_parts:
            for key, value in part.items():
                if key not in merged:
                    # Copy dicts, so merging later parts never changes a dict the caller passed in.
                    merged[key] = dict(cast(dict[str, Any], value)) if isinstance(value, dict) else value
                    continue
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                    continue

                merged[key] = value

        for key in _KEYED_PARTS:
            if isinstance(values := merged.get(key), dict):
                merged[key] = _clean_keyed_part(key, cast(dict[str, Any], values))

        return merged


@dataclass(frozen=True)
class ModelExtractor:
    """Expand Pydantic models into request-part mappings."""

    def __call__(self, model: BaseModel, dump_config: DumpConfig) -> dict[str, Any]:
        """Build request parts from a Pydantic model.

        Args:
            model: Model instance to extract request fields from.
            dump_config: Serialization options passed to ``model_dump``, on top of
                ClientX's defaults (see ``dump_model``).

        Returns:
            dict[str, Any]: Request part mapping derived from the model.
        """
        annotation_map = model_annotations(type(model))
        dump = dump_model(model, dump_config)
        return self.build_request_arguments(dump, annotation_map)

    def build_request_arguments(
        self, dump: dict[str, Any], annotation_map: Mapping[str, NamedAnnotation]
    ) -> dict[str, dict[str, Any]]:
        """Build request parts based on a model dump and annotation mapping.

        Args:
            dump: Model dump to map into request parts. This dict is mutated as
                fields are assigned.
            annotation_map: Mapping of model field names (and aliases) to annotations.

        Returns:
            dict[str, dict[str, Any]]: Request-part mapping grouped by
                request part. A field marked with a request part is merged into
                that section if it's a mapping. In ``params``, ``headers``, and
                ``data``, any other value is sent under the field's ``key``, or
                under its dumped name. Remaining fields default to ``json``.
        """
        request: defaultdict[str, dict[str, Any]] = defaultdict(dict)

        for key in list(dump):
            marker = annotation_map[key].part
            if part := marker.request_part:
                value = dump.pop(key)
                if _sends_single_value(part, marker.key, value, whole_part=False):
                    request[part][marker.key or _default_name(key, part)] = value
                else:
                    request[part].update(value)

        if dump:
            request["json"].update(**dump)

        return request
