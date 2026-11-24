# OpenAPI → ClientX generator (prototype)

`generate.py` reads an OpenAPI 3.x document and writes a ClientX client module
that you don't edit by hand. It contains Pydantic models for
`components.schemas`, one `Resource` per tag, one decorated method per
operation, and an `httpx2.Auth` class for each API-key security scheme.

```bash
uv run python prototypes/openapi_gen/generate.py prototypes/openapi_gen/petstore3.yaml \
    -o prototypes/openapi_gen/petstore.py --class-name PetstoreClient
uv run pytest prototypes/openapi_gen --no-cov
```

`petstore3.yaml` is the [Swagger Petstore 3](https://github.com/swagger-api/swagger-petstore)
spec, and `petstore.py` is what the generator writes from it. A test checks
that the generator still writes exactly that file.

## Mapping

| OpenAPI | Generated |
|---|---|
| `servers[0].url` | `base_url=` on the client class |
| tag | `Resource` with `prefix=` set to the literal segments its paths share, and `tags=[tag]` |
| `operationId` | snake_case method name |
| path param | plain parameter. The placeholder is renamed in the template (`{petId}` → `{pet_id}`) |
| query / header param | `Query()` / `Header()`, with `alias=` when the name changes and `description=` |
| `application/json` body | lone `Json()` parameter, named after its schema |
| form / multipart body | one `Form()` or `File()` per property |
| any other body | `Body()` (`bytes`, or `str` for `text/*`) |
| first 2xx response | the return annotation. No content is `-> None` |
| `summary` + `description` | docstring, which becomes the tool description |
| inline `enum` | `Literal[...]` |
| camelCase property | snake_case field with `alias=` |

Whatever it can't map goes into a `# TODO(openapi):` comment above the
endpoint and a warning on stderr.

## What Petstore showed

- **It needs no runtime support.** All 19 operations map onto ClientX's
  existing API, the module imports without a `DefinitionError`, it passes
  pyright strict and ruff, and `list_tools` turns every operation into a tool.
- **A ClientX bug.** For a model with aliased fields, a tool's `output_schema`
  uses the aliases (`petId`), but `Tool.call()` returns the field names
  (`pet_id`). In `_tools.py`, `json_schema(mode="serialization")` defaults to
  `by_alias=True`, while `dump_python` defaults to `by_alias=False`. The strict
  `xfail` test records it.
- **JSON string responses.** `loginUser` declares `application/json` with
  `type: string`, but ClientX decodes `-> str` as the raw text. Petstore really
  sends text, so it works here, but an API that sends `"token"` would come
  back with its quotes.
- **Response headers** (`X-Rate-Limit`) have no typed form. The only option is
  `-> Response`.
- **Other content types** (XML, and form as an alternative to JSON) are dropped
  with a warning: one body type per endpoint.
- **OAuth2** isn't generated. Pass `auth=` yourself.
- **Not exercised by Petstore:** query styles other than repeated keys
  (`deepObject`, `explode: false`), cookies (there's no `Cookie()` helper, by
  design), several 2xx responses, typed error bodies, `allOf` with more than
  one schema, discriminated unions, and remote `$ref`s.
