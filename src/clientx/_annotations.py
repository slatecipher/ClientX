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
class Part:
    """Send a parameter or model field to a request part.

    Use the helper for the part you want: ``Query``, ``Header``, ``Form``, ``Body``,
    or ``File``. ``Part`` itself is for a request part chosen in code, and for
    ``isinstance`` checks in tooling: every helper is a ``Part``.

    In query parameters, headers, and form data, a mapping or a Pydantic model is
    merged into the part, and any other value is sent under ``key``, or under the
    parameter or field name without one (with hyphens instead of underscores for
    headers). A ``None`` value is left out.

    Attributes:
        request_part: The request part: a ``RequestPart`` member, its string value,
            or ``None``. Strings are converted to ``RequestPart``.
        key: The name a single value is sent under in query parameters, headers,
            or form data. Ignored for ``json`` and ``files``.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model,
            on top of ClientX's defaults (``mode="json"``, ``by_alias=True``).
    """

    request_part: RequestPartName | RequestPart | None = field(default=None)
    dump_config: DumpConfig = field(kw_only=True, default_factory=DumpConfig)
    key: str | None = field(default=None)

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


@dataclass
class Query(Part):
    """Send the value as query parameters.

    ``Annotated[int | None, Query("userId")]`` sends ``?userId=1``, and nothing when
    the value is ``None``. Without a key, a single value is sent under the parameter
    name, and a mapping or model is merged into the query parameters.

    Attributes:
        key: The query parameter name. Defaults to the parameter or field name.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
    """

    request_part: RequestPartName | RequestPart | None = field(default=RequestPart.PARAMS, init=False)


@dataclass
class Header(Part):
    """Send the value as headers.

    ``Annotated[str, Header("Authorization")]`` sends an ``Authorization`` header.
    Without a key, a single value is sent under the parameter name with hyphens
    instead of underscores (``request_id`` becomes ``request-id``), and a mapping or
    model is merged into the headers. Numbers and booleans are sent as text.

    Attributes:
        key: The header name, used as given. Defaults to the parameter or field name,
            with hyphens instead of underscores.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
    """

    request_part: RequestPartName | RequestPart | None = field(default=RequestPart.HEADERS, init=False)


@dataclass
class Form(Part):
    """Send the value as form data (``application/x-www-form-urlencoded``).

    ``Annotated[str, Form("username")]`` sends ``username=...``. Without a key, a
    single value is sent under the parameter name, and a mapping or model is merged
    into the form data.

    Attributes:
        key: The form field name. Defaults to the parameter or field name.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
    """

    request_part: RequestPartName | RequestPart | None = field(default=RequestPart.DATA, init=False)


@dataclass
class Body(Part):
    """Send the value as the JSON body.

    The value is sent as given: a Pydantic model is dumped (by alias, in JSON mode),
    and any other value must be JSON-serializable. For a PATCH, send only the fields
    that were set with ``Body(dump_config=DumpConfig(exclude_unset=True))``.

    Attributes:
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
    """

    request_part: RequestPartName | RequestPart | None = field(default=RequestPart.JSON, init=False)
    key: str | None = field(default=None, init=False)


@dataclass
class File(Part):
    """Send the value as multipart file uploads.

    The value is passed to httpx2 as ``files``: a mapping of field names to file
    contents, file objects, or ``(filename, content, content_type)`` tuples.

    Attributes:
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
    """

    request_part: RequestPartName | RequestPart | None = field(default=RequestPart.FILES, init=False)
    key: str | None = field(default=None, init=False)
