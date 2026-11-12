from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, TypedDict

from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from clientx._client_types import RequestPartName


class DumpConfig(TypedDict, total=False):
    """The ``pydantic.BaseModel.model_dump`` options ClientX supports.

    This is a chosen subset of ``model_dump``'s keyword arguments, not a full copy:
    a Pydantic option is added here only when building a request needs it, and every
    key exists in the lowest Pydantic version ClientX supports. Because
    ``total=False``, all keys are optional. ClientX dumps with ``mode="json"`` and
    ``by_alias=True``; any other option that is left out uses Pydantic's default.

    Attributes:
        mode: Serialization mode. ``"json"`` (ClientX's default) gives JSON-compatible
            output; ``"python"`` keeps non-JSON Python objects.
        include: Include selector using Pydantic's include/exclude specification.
        exclude: Exclude selector using Pydantic's include/exclude specification.
        context: Extra context passed into Pydantic serializers. Defaults to ``None`` when not provided.
        by_alias: Uses field aliases as output keys when ``True`` (ClientX's default).
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
    """Base class of the helpers: ``Query``, ``Header``, ``Form``, ``Body``, ``File``, and ``PathParam``.

    Internal: users choose a request part by choosing a helper, never by name. Each
    helper sets ``request_part`` as a class constant, so it isn't an argument, a
    dataclass field, or part of the repr. An empty ``Part()`` stands for "no request
    part" when an annotation has no helper.

    In query parameters, headers, and form data, a mapping or a Pydantic model is
    merged into the part, and any other value is sent under ``key``, or under the
    parameter or field name without one (with hyphens instead of underscores for
    headers). A ``None`` value is left out.

    Attributes:
        request_part: Class constant: the request part, as the name of the httpx2
            argument it's passed as (``"params"``, ``"headers"``, ``"data"``,
            ``"json"``, or ``"files"``), or ``None``.
        key: The name a single value is sent under in query parameters, headers,
            or form data.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model,
            on top of ClientX's defaults (``mode="json"``, ``by_alias=True``).
        description: Describes the parameter or field for AI tools: it becomes the
            ``description`` in ``clientx.tools`` and MCP argument schemas. A
            ``pydantic.Field(description=...)`` on the same parameter wins.
    """

    request_part: ClassVar[RequestPartName | None] = None
    dump_config: DumpConfig = field(kw_only=True, default_factory=DumpConfig)
    key: str | None = field(default=None)
    description: str | None = field(kw_only=True, default=None)

    def __get_pydantic_json_schema__(self, core_schema: CoreSchema, handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        """Add ``description`` to the JSON Schema Pydantic builds for the annotated type.

        Pydantic applies a field's own ``Field(description=...)`` after this, so that one wins.
        """
        json_schema = handler(core_schema)
        if self.description is not None:
            json_schema = {**json_schema, "description": self.description}
        return json_schema


@dataclass
class Query(Part):
    """Send the value as query parameters.

    ``Annotated[int | None, Query("userId")]`` sends ``?userId=1``, and nothing when
    the value is ``None``. Without a key, a single value is sent under the parameter
    name, and a mapping or model is merged into the query parameters.

    Attributes:
        key: The query parameter name. Defaults to the parameter or field name.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
        description: Describes the parameter or field for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = "params"


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
        description: Describes the parameter or field for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = "headers"


@dataclass
class Form(Part):
    """Send the value as form data (``application/x-www-form-urlencoded``).

    ``Annotated[str, Form("username")]`` sends ``username=...``. Without a key, a
    single value is sent under the parameter name, and a mapping or model is merged
    into the form data.

    Attributes:
        key: The form field name. Defaults to the parameter or field name.
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
        description: Describes the parameter or field for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = "data"


@dataclass
class Body(Part):
    """Send the value as the JSON body.

    The value is sent as given: a Pydantic model is dumped (by alias, in JSON mode),
    and any other value must be JSON-serializable. For a PATCH, send only the fields
    that were set with ``Body(dump_config=DumpConfig(exclude_unset=True))``.

    Attributes:
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
        description: Describes the parameter or field for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = "json"
    key: str | None = field(default=None, init=False)


@dataclass
class File(Part):
    """Send the value as multipart file uploads.

    The value is passed to httpx2 as ``files``: a mapping of field names to file
    contents, file objects, or ``(filename, content, content_type)`` tuples.

    Attributes:
        dump_config: Options for ``model_dump`` when the value is a Pydantic model.
        description: Describes the parameter or field for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = "files"
    key: str | None = field(default=None, init=False)


@dataclass
class PathParam(Part):
    """Describe a path parameter for AI tools.

    ``Annotated[int, PathParam(description="The user's ID")]`` puts the description in the
    tool's argument schema. It only describes: the parameter is still matched to its
    ``{placeholder}`` by name. A parameter marked ``PathParam()`` must have a placeholder in
    the endpoint's path, including a ``Resource`` prefix, or ``EndpointSignatureError``
    is raised when the class is defined. It can't be used on a model field.

    It isn't named ``Path``, unlike FastAPI's, because ``pathlib.Path`` imported in the
    same module would shadow it silently: on Python 3.12 and 3.13, ``pathlib.Path``
    accepts ``description=`` with only a ``DeprecationWarning``, and the description
    would be lost.

    Attributes:
        description: Describes the parameter for AI tools.
    """

    request_part: ClassVar[RequestPartName | None] = None
    dump_config: DumpConfig = field(init=False, default_factory=DumpConfig)
    key: str | None = field(default=None, init=False)
