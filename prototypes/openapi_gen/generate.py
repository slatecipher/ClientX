"""Generate a ClientX client module from an OpenAPI 3.0 or 3.1 document.

A prototype. It writes Python source: Pydantic models for
``components.schemas``, one ``Resource`` per tag, and one decorated method per
operation. It handles what the Petstore spec uses, and reports what it skips
as ``# TODO(openapi):`` comments in the output and as warnings on stderr, so
nothing is dropped silently.

Usage::

    python prototypes/openapi_gen/generate.py SPEC [-o OUT] [--class-name X]

The output is formatted with ruff when it's installed. Importing it runs
ClientX's own checks: a mapping the generator gets wrong raises
``DefinitionError`` there.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

type Schema = dict[str, Any]

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")

# Request content types, most preferred first. XML isn't supported.
JSON_TYPES = ("application/json",)
FORM_TYPES = ("application/x-www-form-urlencoded",)
MULTIPART_TYPES = ("multipart/form-data",)

# Names a resource attribute or a client-level endpoint can't take: they're
# attributes of httpx2.Client. Read from ClientX itself when it's importable.
try:
    from clientx import ClientX

    CLIENT_NAMES = frozenset(dir(ClientX))
except ImportError:  # pragma: no cover - the generator runs without clientx
    CLIENT_NAMES = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "send", "request"})


# --- Names --------------------------------------------------------------------
def snake(name: str) -> str:
    """Turn ``petId``, ``X-Rate-Limit`` or ``api_key`` into a Python name."""
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = name.strip("_").lower() or "value"
    if name[0].isdigit():
        name = f"n_{name}"
    if keyword.iskeyword(name) or name == "self":
        name += "_"
    return name


def pascal(name: str) -> str:
    """Turn a schema or tag name into a class name."""
    parts = re.split(r"[^0-9a-zA-Z]+", name)
    result = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return result if result and not result[0].isdigit() else f"N{result}"


def docstring(lines: list[str], indent: str) -> list[str]:
    """Return a docstring, wrapped at 80 columns, as source lines."""
    paragraphs = [p for p in (" ".join(line.split()) for line in lines) if p]
    if not paragraphs:
        return []
    width = 80 - len(indent)
    summary = paragraphs[0].replace('"""', "'''")
    if not summary.endswith("."):
        summary += "."
    summary_lines = textwrap.wrap(summary, width - 3)
    if len(summary_lines) == 1 and len(paragraphs) == 1:
        return [f'{indent}"""{summary}"""']
    # The summary must fit on one line; a long one becomes the first paragraph.
    if len(summary_lines) > 1:
        paragraphs = ["", *paragraphs]
        first = "Call the endpoint."
    else:
        first = summary
        paragraphs = paragraphs[1:]
    out = [f'{indent}"""{first}']
    for paragraph in paragraphs:
        if not paragraph:
            continue
        out.append("")
        out.extend(f"{indent}{line}" for line in textwrap.wrap(paragraph.replace('"""', "'''"), width))
    out.append(f'{indent}"""')
    return out


def py_literal(value: object) -> str:
    return repr(value)


# --- The intermediate representation -----------------------------------------
@dataclass
class Param:
    name: str
    annotation: str
    helper: str | None  # None for a path parameter
    default: str | None  # None when required
    description: str = ""

    def source(self) -> str:
        annotation = self.annotation
        if self.helper is not None:
            annotation = f"Annotated[{annotation}, {self.helper}]"
        default = f" = {self.default}" if self.default is not None else ""
        return f"{self.name}: {annotation}{default}"


@dataclass
class Operation:
    name: str
    verb: str
    path: str  # relative to the resource's prefix
    params: list[Param]
    returns: str
    doc: list[str]
    tags: list[str]
    deprecated: bool
    todos: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class ResourceIR:
    tag: str
    class_name: str
    attribute: str
    prefix: str
    description: str
    operations: list[Operation] = field(default_factory=lambda: list[Operation]())


# --- The generator ------------------------------------------------------------
class Generator:
    def __init__(self, spec: Schema, class_name: str | None) -> None:
        self.spec = spec
        self.schemas: dict[str, Schema] = spec.get("components", {}).get("schemas", {})
        self.model_names = {name: pascal(name) for name in self.schemas}
        self.class_name = class_name or pascal(spec.get("info", {}).get("title", "API")) + "Client"
        self.imports: set[str] = {"Annotated"}
        self.abc_imports: set[str] = set()
        self.clientx_imports: set[str] = {"ClientX", "Resource", "method"}
        self.uses: set[str] = set()  # names from datetime, uuid, typing...
        self.warnings: list[str] = []

    # -- Helpers ---------------------------------------------------------------
    def warn(self, where: str, message: str, todos: list[str]) -> None:
        self.warnings.append(f"{where}: {message}")
        todos.append(message)

    def resolve(self, schema: Schema) -> Schema:
        seen = 0
        while "$ref" in schema:
            ref: str = schema["$ref"]
            if not ref.startswith("#/"):
                raise SystemExit(f"Only local $refs are supported: {ref}")
            target: Any = self.spec
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            schema = cast(Schema, target)
            seen += 1
            if seen > 50:
                raise SystemExit(f"$ref cycle at {ref}")
        return schema

    def type_of(self, schema: Schema | None) -> str:
        """Return the Python annotation for a JSON Schema."""
        if not schema:
            self.uses.add("Any")
            return "Any"
        if "$ref" in schema:
            ref: str = schema["$ref"]
            prefix = "#/components/schemas/"
            if ref.startswith(prefix) and ref[len(prefix) :] in self.model_names:
                return self.model_names[ref[len(prefix) :]]
            return self.type_of(self.resolve(schema))
        for combiner in ("oneOf", "anyOf"):
            if combiner in schema:
                options = [self.type_of(cast(Schema, s)) for s in schema[combiner]]
                return " | ".join(dict.fromkeys(options))
        if "allOf" in schema and len(schema["allOf"]) == 1:
            return self.type_of(schema["allOf"][0])
        if "enum" in schema:
            self.uses.add("Literal")
            return f"Literal[{', '.join(py_literal(v) for v in schema['enum'])}]"
        kind = schema.get("type")
        nullable = bool(schema.get("nullable"))
        if isinstance(kind, list):  # OpenAPI 3.1
            kinds = cast(list[str], kind)
            nullable = nullable or "null" in kinds
            rest = [k for k in kinds if k != "null"]
            kind = rest[0] if len(rest) == 1 else None
        annotation = self._plain_type(schema, kind)
        return f"{annotation} | None" if nullable and not annotation.endswith("| None") else annotation

    def _plain_type(self, schema: Schema, kind: object) -> str:
        fmt = schema.get("format")
        if kind == "integer":
            return "int"
        if kind == "number":
            return "float"
        if kind == "boolean":
            return "bool"
        if kind == "string":
            if fmt == "date-time":
                self.uses.add("datetime")
                return "datetime"
            if fmt == "date":
                self.uses.add("date")
                return "date"
            if fmt == "uuid":
                self.uses.add("UUID")
                return "UUID"
            if fmt == "binary":
                return "bytes"
            return "str"
        if kind == "array":
            return f"list[{self.type_of(schema.get('items'))}]"
        if kind == "object" or "properties" in schema or "additionalProperties" in schema:
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict) and not schema.get("properties"):
                return f"dict[str, {self.type_of(cast(Schema, extra))}]"
            self.uses.add("Any")
            return "dict[str, Any]"
        self.uses.add("Any")
        return "Any"

    # -- Models ----------------------------------------------------------------
    def models(self) -> list[str]:
        out: list[str] = []
        for name, raw in self.schemas.items():
            schema = self.resolve(raw)
            class_name = self.model_names[name]
            if schema.get("type") != "object" and "properties" not in schema:
                out += ["", "", f"type {class_name} = {self._plain_type(schema, schema.get('type'))}"]
                continue
            required = set(cast(list[str], schema.get("required", [])))
            out += ["", "", f"class {class_name}(BaseModel):"]
            out += docstring([schema.get("description") or f"The ``{name}`` schema."], "    ")
            properties = cast(dict[str, Schema], schema.get("properties", {}))
            aliased = any(snake(p) != p for p in properties)
            if aliased:
                out.append("    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)")
            if aliased or properties:
                out.append("")
            for prop, prop_schema in properties.items():
                attribute = snake(prop)
                annotation = self.type_of(prop_schema)
                field_args: list[str] = []
                if attribute != prop:
                    field_args.append(f"alias={prop!r}")
                description = self.resolve(prop_schema).get("description")
                if description:
                    field_args.append(f"description={description!r}")
                if prop in required:
                    default = f"Field({', '.join(field_args)})" if field_args else None
                else:
                    if not annotation.endswith("| None") and annotation != "Any":
                        annotation += " | None"
                    default = f"Field(None, {', '.join(field_args)})" if field_args else "None"
                out.append(f"    {attribute}: {annotation}" + (f" = {default}" if default else ""))
        return out

    # -- Operations ------------------------------------------------------------
    def operation(self, path: str, verb: str, op: Schema, path_item: Schema, prefix: str) -> Operation:
        where = f"{verb.upper()} {path}"
        todos: list[str] = []
        name = snake(op.get("operationId") or f"{verb}_{path}")
        params: list[Param] = []
        used: set[str] = set()
        template = path

        raw_params = [*path_item.get("parameters", []), *op.get("parameters", [])]
        merged: dict[tuple[str, str], Schema] = {}
        for raw in raw_params:
            p = self.resolve(cast(Schema, raw))
            merged[(p["in"], p["name"])] = p  # an operation's overrides the path's

        for (location, wire_name), p in merged.items():
            py_name = snake(wire_name)
            if py_name in used:
                py_name = f"{py_name}_{location}"
            schema = cast(Schema, p.get("schema", {}))
            annotation = self.type_of(schema)
            required = bool(p.get("required")) or location == "path"
            default_value = self.resolve(schema).get("default") if schema else None
            description = str(p.get("description") or "")
            helper_args: list[str] = []

            if location == "path":
                # A placeholder can't have an alias: rename it in the template.
                template = template.replace("{" + wire_name + "}", "{" + py_name + "}")
                params.append(Param(py_name, annotation, None, None, description))
                used.add(py_name)
                continue
            if location == "cookie":
                self.warn(where, f"cookie parameter {wire_name!r} skipped: set cookies on the client", todos)
                continue
            if location == "query":
                helper = "Query"
                key = py_name
                style = p.get("style", "form")
                explode = p.get("explode", style == "form")
                is_array = self.resolve(schema).get("type") == "array" if schema else False
                if style == "deepObject" or (is_array and (style != "form" or not explode)):
                    self.warn(
                        where,
                        f"query {wire_name!r} uses style={style}, explode={explode}: sent as repeated keys",
                        todos,
                    )
            else:  # header
                helper = "Header"
                key = py_name.replace("_", "-")
                if wire_name.lower() in ("accept", "content-type", "authorization"):
                    self.warn(where, f"header {wire_name!r} skipped: httpx2 sets it, or auth= does", todos)
                    continue
            if key != wire_name:
                helper_args.append(f"alias={wire_name!r}")
            if description:
                helper_args.append(f"description={description!r}")
            self.clientx_imports.add(helper)
            default: str | None = None
            if default_value is not None:
                default = py_literal(default_value)
            elif not required:
                annotation = annotation if annotation.endswith("| None") else f"{annotation} | None"
                default = "None"
            params.append(Param(py_name, annotation, f"{helper}({', '.join(helper_args)})", default, description))
            used.add(py_name)

        if "requestBody" in op:
            body = self.request_body(where, self.resolve(op["requestBody"]), used, todos)
            params.extend(body)

        # Required parameters first, as Python needs, keeping the spec's order.
        params.sort(key=lambda p: p.default is not None)

        relative = template[len(prefix) :] if prefix and template.startswith(prefix) else template
        doc = [str(op.get("summary") or "")]
        description = str(op.get("description") or "")
        if description and description.rstrip(".") != doc[0].rstrip("."):
            doc.append(description)
        if not any(doc):
            doc = [f"{verb.upper()} {path}"]
        return Operation(
            name=name,
            verb=verb,
            path=relative,
            params=params,
            returns=self.response_type(where, op, todos),
            doc=doc,
            tags=[],
            deprecated=bool(op.get("deprecated")),
            todos=todos,
        )

    def request_body(self, where: str, body: Schema, used: set[str], todos: list[str]) -> list[Param]:
        content = cast(dict[str, Schema], body.get("content", {}))
        required = bool(body.get("required"))
        description = str(body.get("description") or "")

        def pick(choices: Iterable[str]) -> str | None:
            return next((c for c in choices if c in content), None)

        skipped = sorted(set(content) - {pick(JSON_TYPES) or pick(content) or ""})
        if skipped:
            self.warnings.append(f"{where}: request content types not generated: {', '.join(skipped)}")

        def name_for(schema: Schema | None) -> str:
            ref = (schema or {}).get("$ref", "")
            items_ref = (schema or {}).get("items", {}).get("$ref", "") if schema else ""
            base = (
                snake(ref.rsplit("/", 1)[-1])
                if ref
                else snake(items_ref.rsplit("/", 1)[-1]) + "s"
                if items_ref
                else "body"
            )
            return base if base not in used and base != "s" else "body"

        if (json_type := pick(JSON_TYPES)) is not None:
            schema = content[json_type].get("schema")
            annotation = self.type_of(schema)
            self.clientx_imports.add("Json")
            default = None if required else "None"
            if default and not annotation.endswith("| None"):
                annotation += " | None"
            helper = f"Json(description={description!r})" if description else "Json()"
            return [Param(name_for(schema), annotation, helper, default, description)]

        if (form_type := pick(FORM_TYPES) or pick(MULTIPART_TYPES)) is not None:
            schema = self.resolve(content[form_type].get("schema") or {})
            params: list[Param] = []
            props = cast(dict[str, Schema], schema.get("properties", {}))
            req = set(cast(list[str], schema.get("required", [])))
            for prop, prop_schema in props.items():
                py_name = snake(prop)
                annotation = self.type_of(prop_schema)
                is_file = annotation in ("bytes", "list[bytes]")
                helper = "File" if is_file else "Form"
                self.clientx_imports.add(helper)
                args = f"alias={prop!r}" if py_name != prop else ""
                default = None if prop in req else "None"
                if default and not annotation.endswith("| None"):
                    annotation += " | None"
                params.append(Param(py_name, annotation, f"{helper}({args})", default))
            return params

        # Anything else is a raw body: binary, text, XML...
        media = next(iter(content), None)
        if media is None:
            return []
        schema = content[media].get("schema") or {}
        annotation = "str" if media.startswith("text/") and schema.get("format") != "binary" else "bytes"
        self.clientx_imports.add("Body")
        if media != "application/octet-stream":
            self.warn(where, f"raw {media} body: the caller must set Content-Type", todos)
        default = None if required else "None"
        if default:
            annotation += " | None"
        return [Param("body" if "body" not in used else "content", annotation, "Body()", default)]

    def response_type(self, where: str, op: Schema, todos: list[str]) -> str:
        responses = cast(dict[str, Schema], op.get("responses", {}))
        success = [code for code in responses if str(code).startswith("2")]
        if not success:
            return "None"
        if len(success) > 1:
            self.warn(where, f"several success responses ({', '.join(success)}): typed by {success[0]} only", todos)
        response = self.resolve(responses[success[0]])
        if response.get("headers"):
            names = ", ".join(response["headers"])
            self.warn(where, f"response headers ({names}) not typed: return Response to read them", todos)
        content = cast(dict[str, Schema], response.get("content", {}))
        if not content:
            return "None"
        if "application/json" in content:
            schema = content["application/json"].get("schema")
            annotation = self.type_of(schema)
            if annotation == "str":
                # ClientX decodes -> str as the body's text, not as JSON.
                self.warn(where, "JSON string response typed -> str: decoded as raw text, not JSON", todos)
            return annotation
        media = next(iter(content))
        if media == "text/event-stream":
            self.abc_imports.add("Iterator")
            return "Iterator[str]"
        if media.startswith("text/"):
            return "str"
        if media == "application/octet-stream" or "image/" in media:
            return "bytes"
        self.warn(where, f"response type {media} not decoded: returns Response", todos)
        self.clientx_imports.add("Response")
        return "Response"

    # -- Resources -------------------------------------------------------------
    def resources(self) -> tuple[list[ResourceIR], list[Operation]]:
        by_tag: dict[str, list[tuple[str, str, Schema, Schema]]] = {}
        untagged: list[tuple[str, str, Schema, Schema]] = []
        for path, item in cast(dict[str, Schema], self.spec.get("paths", {})).items():
            for verb in HTTP_METHODS:
                if verb in item:
                    op = cast(Schema, item[verb])
                    entry = (path, verb, op, item)
                    tags = cast(list[str], op.get("tags") or [])
                    (by_tag.setdefault(tags[0], []) if tags else untagged).append(entry)
                    if len(tags) > 1:
                        self.warnings.append(f"{verb.upper()} {path}: only its first tag, {tags[0]!r}, is used")

        tag_docs = {t["name"]: t.get("description", "") for t in self.spec.get("tags", [])}
        resources: list[ResourceIR] = []
        taken = set(self.model_names.values()) | {self.class_name}
        for tag, entries in by_tag.items():
            prefix = common_prefix([path for path, *_ in entries])
            class_name = pascal(tag) + "Resource"
            while class_name in taken:
                class_name += "_"
            taken.add(class_name)
            attribute = snake(tag)
            if attribute in CLIENT_NAMES:
                attribute += "_"
            resource = ResourceIR(tag, class_name, attribute, prefix, tag_docs.get(tag, ""))
            seen: set[str] = set()
            for path, verb, op, item in entries:
                operation = self.operation(path, verb, op, item, prefix)
                while operation.name in seen:
                    operation.name += "_"
                seen.add(operation.name)
                resource.operations.append(operation)
            resources.append(resource)

        top: list[Operation] = []
        for path, verb, op, item in untagged:
            operation = self.operation(path, verb, op, item, "")
            if operation.name in CLIENT_NAMES:
                operation.name += "_"
            top.append(operation)
        return resources, top

    # -- Output ----------------------------------------------------------------
    def render_operation(self, op: Operation) -> list[str]:
        out = [""]
        for todo in op.todos:
            out += textwrap.wrap(todo, 80, initial_indent="    # TODO(openapi): ", subsequent_indent="    #   ")
        options: list[str] = [repr(op.path)] if op.path else []
        if op.deprecated:
            options.append('deprecated="Deprecated in the OpenAPI document."')
        out.append(f"    @method.{op.verb}({', '.join(options)})")
        params = ", ".join(["self", *(p.source() for p in op.params)])
        out.append(f"    def {op.name}({params}) -> {op.returns}:")
        out += docstring(op.doc, "        ")
        out.append("        ...")
        return out

    def render(self) -> str:
        resources, top = self.resources()
        models = self.models()
        servers = cast(list[Schema], self.spec.get("servers") or [])
        base_url = servers[0]["url"] if servers else None
        if base_url and not re.match(r"^https?://", base_url):
            self.warnings.append(f"server URL {base_url!r} isn't absolute: base_url left out")
            base_url = None

        body: list[str] = []
        for resource in resources:
            class_args = [f"prefix={resource.prefix!r}", f"tags=[{resource.tag!r}]"]
            body += ["", "", f"class {resource.class_name}(Resource, {', '.join(class_args)}):"]
            body += docstring([resource.description or f"The ``{resource.tag}`` operations."], "    ")
            for op in resource.operations:
                body += self.render_operation(op)

        info = self.spec.get("info", {})
        client_args = ["ClientX"]
        if base_url:
            client_args.append(f"base_url={base_url!r}")
        body += ["", "", f"class {self.class_name}({', '.join(client_args)}):"]
        body += docstring([str(info.get("title") or "The API client.")], "    ")
        body.append("")
        body += [f"    {r.attribute} = {r.class_name}()" for r in resources]
        for op in top:
            body += self.render_operation(op)

        body += self.security()

        header = [
            f'"""Generated from {info.get("title", "an OpenAPI document")} {info.get("version", "")}.',
            "",
            "Don't edit: regenerate with prototypes/openapi_gen/generate.py.",
            '"""',
            "",
        ]
        stdlib: list[str] = []
        dt = sorted(n for n in self.uses if n in ("date", "datetime"))
        if dt:
            stdlib.append(f"from datetime import {', '.join(dt)}")
        typing_names = sorted(self.imports | (self.uses & {"Any", "Literal"}))
        if self.abc_imports:
            stdlib.append(f"from collections.abc import {', '.join(sorted(self.abc_imports))}")
        stdlib.append(f"from typing import {', '.join(typing_names)}")
        if "UUID" in self.uses:
            stdlib.append("from uuid import UUID")
        uses_auth = bool(self.abc_imports & {"Generator"})
        third = []
        if uses_auth:
            third.append("import httpx2")
        third.append(f"from clientx import {', '.join(sorted(self.clientx_imports))}")
        pydantic_names = ["BaseModel"]
        if any("Field(" in line for line in models):
            pydantic_names.append("Field")
        if any("ConfigDict" in line for line in models):
            pydantic_names.append("ConfigDict")
        third.append(f"from pydantic import {', '.join(sorted(pydantic_names))}")
        return "\n".join([*header, *sorted(stdlib), "", *third, *models, *body]) + "\n"

    def security(self) -> list[str]:
        """Return an ``httpx2.Auth`` per API-key scheme; warn about the rest."""
        out: list[str] = []
        schemes = cast(dict[str, Schema], self.spec.get("components", {}).get("securitySchemes", {}))
        for name, scheme in schemes.items():
            scheme = self.resolve(scheme)
            if scheme.get("type") == "apiKey" and scheme.get("in") in ("header", "query"):
                class_name = pascal(name) + "Auth"
                where = "headers" if scheme["in"] == "header" else "url params"
                out += ["", "", f"class {class_name}(httpx2.Auth):"]
                out += docstring([f"Send the ``{name}`` API key in the {where}."], "    ")
                out += [
                    "",
                    "    def __init__(self, key: str) -> None:",
                    "        self.key = key",
                    "",
                    "    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:",
                    '        """Add the key to the request."""',
                ]
                if scheme["in"] == "header":
                    out.append(f"        request.headers[{scheme['name']!r}] = self.key")
                else:
                    out.append(f"        request.url = request.url.copy_merge_params({{{scheme['name']!r}: self.key}})")
                out.append("        yield request")
                self.abc_imports.add("Generator")
            elif scheme.get("type") == "http" and scheme.get("scheme") in ("basic", "bearer"):
                self.warnings.append(f"security scheme {name!r}: pass auth= ({scheme['scheme']}) to the client")
            else:
                self.warnings.append(f"security scheme {name!r} ({scheme.get('type')}) not generated")
        return out


def common_prefix(paths: list[str]) -> str:
    """Return the literal path segments every path starts with."""
    split = [p.strip("/").split("/") for p in paths]
    prefix: list[str] = []
    for segments in zip(*split, strict=False):
        first = segments[0]
        if "{" in first or any(s != first for s in segments):
            break
        prefix.append(first)
    # Keep one segment for an endpoint's own path when every path is the prefix.
    return "/" + "/".join(prefix) if prefix else ""


def load(path: Path) -> Schema:
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml  # noqa: PLC0415 - optional, only for YAML input

        return cast(Schema, yaml.safe_load(text))
    return cast(Schema, json.loads(text))


def main() -> None:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--class-name")
    args = parser.parse_args()

    spec = load(args.spec)
    version = str(spec.get("openapi", ""))
    if not version.startswith("3."):
        raise SystemExit(f"Only OpenAPI 3.x is supported, not {version or 'Swagger 2'!r}")
    generator = Generator(spec, args.class_name)
    source = generator.render()

    if args.output:
        args.output.write_text(source)
        try:
            subprocess.run(["ruff", "check", "--quiet", "--fix", "--select", "I", str(args.output)], check=True)
            subprocess.run(["ruff", "check", "--quiet", "--fix", "--select", "I", str(args.output)], check=True)
            subprocess.run(["ruff", "format", "--quiet", str(args.output)], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"warning: ruff format failed: {error}", file=sys.stderr)
    else:
        sys.stdout.write(source)
    for warning in generator.warnings:
        print(f"warning: {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()
