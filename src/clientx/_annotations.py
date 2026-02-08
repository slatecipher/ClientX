from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, TypedDict

from clientx._client_types import RequestPartName


class DumpConfig(TypedDict, total=False):
    """Options forwarded to ``pydantic.BaseModel.model_dump``.

    This typed dictionary mirrors the keyword arguments supported by Pydantic's
    ``model_dump`` method. Because ``total=False``, all keys are optional.
    When omitted, each option falls back to Pydantic's default behavior.

    Attributes:
        mode: Serialization mode. Use ``"json"`` for JSON-compatible output or
            ``"python"`` to allow non-JSON Python objects.
        include: Include selector using Pydantic's include/exclude specification.
        exclude: Exclude selector using Pydantic's include/exclude specification.
        context: Extra context passed into Pydantic serializers. Defaults to ``None`` when not provided.
        by_alias: Uses field aliases as output keys when ``True``.
        exclude_unset: Excludes fields that were not explicitly set when ``True``.
        exclude_defaults: Excludes fields with default values when ``True``.
        exclude_none: Excludes fields with ``None`` values when ``True``.
        exclude_computed_fields: Excludes computed fields when ``True``.
        round_trip: Emits values suitable for round-tripping non-idempotent types when ``True``.
        warnings: Serialization error behavior. ``False``/``"none"`` ignores errors,
            ``True``/``"warn"`` emits warnings, and ``"error"`` raises.
        serialize_as_any: Enables duck-typing serialization behavior when ``True``.
    """

    mode: Literal["json", "python"] | str
    include: Any
    exclude: Any
    context: dict[str, Any] | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    exclude_computed_fields: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    serialize_as_any: bool


@dataclass
class FieldX:
    """Field-level metadata used by the client request builder.

    Attributes:
        request_part: Target request payload section for a field. Accepts either
            a ``RequestPart`` member, a supported string value, or ``None``.
            Defaults to ``None``.
        dump_config: Optional Pydantic dump options used when serializing the
            field value. Defaults to an empty ``DumpConfig``.
    """

    request_part: RequestPartName | RequestPart | None = field(default=None)
    dump_config: DumpConfig = field(kw_only=True, default_factory=DumpConfig)

    def __post_init__(self):
        """Normalize string ``request_part`` values into ``RequestPart`` members."""
        if isinstance(self.request_part, str):
            self.request_part = RequestPart(self.request_part)


class RequestPart(StrEnum):
    """Supported request payload sections for serialized fields.

    Attributes:
        PARAMS: Field is serialized into request query parameters (``params``).
        FILES: Field is serialized into multipart file payloads (``files``).
        DATA: Field is serialized into form body data (``data``).
        JSON: Field is serialized into JSON request body (``json``).
        HEADERS: Field is serialized into request headers (``headers``).
    """

    PARAMS = "params"
    FILES = "files"
    DATA = "data"
    JSON = "json"
    HEADERS = "headers"

    @classmethod
    def get(cls, value: str) -> RequestPart | None:
        """Return the matching enum member for a string, if present.

        Args:
            value: Candidate request section string.

        Returns:
            The matching ``RequestPart`` member, or ``None`` when there is no match.
        """
        return cls(value) if value in RequestPart else None
