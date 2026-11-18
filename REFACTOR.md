# Client refactor: status

Branch `experiment/signature-info`, last updated 2026-11-16. A rewrite of `src/clientx` that's
simpler and easier to read, ported from the old code one small step at a time. Delete this file when
the port is done.

The old code is on `mainline`; `src/clientx/pre/`, which kept a copy for reference, was deleted on
2026-11-17. Read an old module with `git show mainline:src/clientx/<module>.py`: `tools.py` and
`mcp.py` for item 11, and `_endpoint_context.py` (`Endpoint._validate`) for argument validation (#136,
after the release).

## Decisions so far

- `ClientX` and `AsyncClientX` subclass `httpx2.Client` and `httpx2.AsyncClient` (no wrapped
  `__clientx_client__`). Context managers, `close`, `send`, `build_request` come from httpx2.
- So httpx2's public names (`get`, `send`, `stream`, `headers`, ...) can't be endpoint names on a
  client. Accepted by design: those names are free on a `Resource`.
- `base_url` is a required `__init__` argument; the `base_url=` class argument is dropped for now.
  `user_agent=` is still a class argument.
- Each client has a real `__init__` (no `if TYPE_CHECKING` signatures). `HttpxClientOptions` holds
  only httpx2's options; `_configure()` applies `user_agent` and `raise_for_status`.
- Class-definition rules live in `_class_setup.py`, apart from the classes in `_client.py`.
  `_registry.py` stays a plain lookup. `__init_subclass__` sits on each of the four concrete bases.
- Request-part helpers (`clientx.arguments`) count only inside `Annotated` on endpoint parameters,
  by design: no annotation and default to reconcile.
- Decoding is driven by the return annotation; `decoder=` (any `Callable[[Response], T]`) overrides.
  The old decoder classes aren't ported (`decoder=Model.from_response` replaces `FromResponseDecoder`).
- `inspect_signature` describes every parameter as written; `Endpoint` owns the rule that the first
  parameter receives the client or resource.
- Three exception classes instead of the old twelve (`clientx/exceptions.py`): `ClientXError`, the base;
  `DefinitionError(ClientXError, TypeError)` for every mistake in how a client, resource or endpoint is
  written (nearly all raised when the class is defined; nobody catches them, so the message is what
  matters); and `ArgumentError(ClientXError, ValueError)` for argument values that can't be sent (the old
  `PathValueError` and `ArgumentValidationError`), with `.parameter`. Like Pydantic's `PydanticUserError`
  and FastAPI's `FastAPIError`. HTTP errors stay httpx2's. Python's own `TypeError` for a call that
  doesn't fit the signature, and its `NameError` for an annotation that can't be resolved, aren't wrapped
  (wrapping the `NameError` with the endpoint's name was considered; revisit later).
- `deprecated=` takes the warning's message, a `str`. The wrapper emits the `DeprecationWarning` itself
  with `stacklevel=2`, so it names the caller's line and is shown by Python's default filters.
  `DeprecatedMessage` and the "any callable" form are gone. The old `stacklevel=4` pointed into
  clientx's `_decorators.py`, so outside test runners the warning was hidden.
- An endpoint's `timeout=` follows httpx2: it defaults to `USE_CLIENT_DEFAULT` (the client's timeout),
  and `None` means no timeout. Unlike `raise_for_status=`, where `None` means the client's setting. The old code read `timeout=None` as the client's.
- Request building follows FastAPI's rules, run the other way (agreed 2026-11-17):
  - A parameter without a helper goes to the path if a placeholder names it; to the JSON body if it's
    a model, mapping, list or dataclass; otherwise to the query string. Decided when the class is defined.
  - A helper on a model parameter sends all its fields to that part. Helpers on model fields aren't
    supported (`DefinitionError`).
  - One JSON parameter is the whole body; several are keyed by parameter name. A lone plain value is
    keyed by its name too (agreed 2026-11-17): `title: Annotated[str, Json()]` sends `{"title": ...}`.
    No `embed` option.
  - With several helpers on one parameter, the last one wins. A helper nested inside another type,
    such as `Annotated[str, Header()] | None`, raises `DefinitionError`.
  - A query parameter is a plain value or a list of plain values (a repeated key); a header is a plain
    value (agreed 2026-11-17). Values become text the same way everywhere: an enum's value, ISO 8601
    for a datetime, JSON text for a number or bool. `None` is left out of the query and headers.
  - No `Cookie` helper (agreed 2026-11-17): httpx2 is deprecating per-request cookies, so cookies go
    on the client.
  - A parameter's name never picks its part (agreed 2026-11-17): the old rule that `headers`, `params`,
    `json`... send that whole part is gone. A mapping with a helper is spread into its part instead.
  - A default inside a helper, such as `Query(default=1)` or `default_factory=`, raises
    `DefinitionError` (agreed 2026-11-17): defaults go after `=`, where `bind` and type checkers see them.
  - A keyed JSON value that's `None` is left out, as in the query, headers and forms (agreed
    2026-11-17), so optional PATCH fields aren't sent as `null`. A lone model or dict is sent whole,
    `null`s included. Open: a way to send an explicit `null` for a keyed parameter (JSON Merge Patch,
    RFC 7396, uses `null` to delete a field).
  - Defaults are sent (agreed 2026-11-17): `bind()` fills them in, so with `page: int = 1`,
    `api.list()` sends `?page=1`, as a Python call would. `| None = None` lets the server decide. The
    alternative, sending only what the caller passed (generated SDKs' `NOT_GIVEN`/`UNSET`), is in #135,
    with explicit `null` and unset model fields.
  - `DumpConfig` isn't ported (agreed 2026-11-17): the helpers wrap `pydantic.Field`, which has no
    place for it, and models control their own serialization (aliases, `Field(exclude=True)`,
    serializers). Its main use, `exclude_unset` for PATCH bodies, is decided in #135; if needed, it
    comes back as a small separate `Annotated` marker.
  - An endpoint sends one kind of body: JSON, raw content (one `Body()`), or a form (`Form()`, plus
    `File()` for multipart). Any other mix raises `DefinitionError` (agreed 2026-11-17): httpx2 sends
    only one and silently drops the rest. Open: a JSON part inside a multipart form, as in Discord's
    `payload_json` (httpx2 sends one from a `files` entry `(None, json_text, "application/json")`).

## Done

| Module | What it does now |
|---|---|
| `_client.py` | `ClientX`, `AsyncClientX`, `Resource`, `AsyncResource`; `_configure`; `client_of(owner, kind)`; each base's `__clientx_is_async__` flag; `_BaseResource.__set_name__` |
| `_class_setup.py` | `set_up_client`, `set_up_resource`: one-kind check, reserved-name check, endpoint-kind check, claiming endpoints (`owner`), resource prefix and tags, then each endpoint's `set_up_request()`; `check_mount` |
| `_registry.py` | `register_endpoint_function`, `endpoint_for` (stores `(wrapper, endpoint)` pairs) |
| `_endpoint.py` | `Endpoint` dataclass; `__post_init__` checks the first parameter and the return annotation, sets `stream`, resolves `decoder`; `bind`, `parameters()`; `request` (the `RequestPlan`), `set_up_request()`, `request_arguments()` (adds `timeout`) |
| `_signature.py` | `inspect_signature`, `SignatureInfo`, `ParameterInfo`, `ReturnInfo`; expands PEP 695 `type` aliases; unresolvable hints raise; a parameter's last helper wins; `unwrap_annotated` |
| `_decoding.py` | `is_stream`, `default_decoder`, `decode`/`adecode` (stream closing), `raise_status_error`/`araise_status_error` |
| `_method.py` | the verb decorator and the sync/async wrappers: warn if deprecated, bind, build the request from `endpoint.request_arguments()` (path, `timeout`), send (`stream=`), raise for 4xx/5xx, decode |
| `_types.py`, `arguments.py`, `_arguments.py` | option TypedDicts, shared aliases; the `Field`-based request-part helpers (no `Cookie`) |
| `exceptions.py` | `ClientXError`, `DefinitionError` (every check above raises it), `ArgumentError` (path values) |
| `_request.py` | `plan_request(template, parameters)` places each parameter (path, helper, or inferred), checks the rules (one kind of body, no default inside a helper...), and returns a `RequestPlan`: the parsed path, a `PlannedParameter` per value sent under a name (query, headers, form, files, JSON fields) or a `SpreadParameter` per model, dataclass or mapping spread into a part, and the `body` parameter, if one is the whole body (raw content, or a lone JSON model, mapping or list). `RequestPlan.build(arguments)` renders the path and fills the parts (`PlannedParameter.encode`, `_to_text`) |

## Missing functionality (besides docs and tests)

Suggested order:

1. [x] `src/clientx/py.typed`: back in place, and the built wheel includes it.
2. [x] Request building, in `_request.py` (replaces the old `_request_factory.py` and
   `_annotation_extractor.py`, ~650 lines). One plan per endpoint, built at class setup after the
   resource prefix is joined; the rules are in Decisions. The open items are listed under each step:
   - [x] path templates (`{name}`, `{name:path}`, `{{ }}`), sent by the wrappers. Checked at class
     setup: each placeholder names a parameter; `Url()` needs a placeholder; a placeholder's parameter
     has no other helper. Left for the next step: path parameters must be plain values
   - [x] query and headers: inference, the key sent (alias; `_` to `-` for headers), dropping `None`,
     value conversion; `DefinitionError` for a nested helper, a non-plain path parameter, a header
     list, or a query type that isn't a plain value or a list of them. Parameters for the parts below
     are planned as not sent yet, and ignored. Open: a non-ASCII header value fails in httpx2 with
     `UnicodeEncodeError` at call time (could be an `ArgumentError`)
   - [x] bodies (`json`, `content`, `data`, `files`), the one-kind-of-body check, and the
     `default=`-inside-a-helper check. JSON is serialized by the value's own type, with aliases. Open:
     several files under one name (a `File()` parameter takes one file); drop
     `ParameterInfo.httpx_argument_spec`, which nothing reads now that there's no `embed`
   - [x] models, dataclasses and mappings with a `Query()`, `Header()` or `Form()` helper, spread into
     that part (`SpreadParameter`): fields under their alias or name (`-` for `_` in headers), a
     mapping's keys as given, the later parameter winning on a clash. A helper on a model's field raises
     `DefinitionError`. The `arguments.py` docstrings now describe parameter-level helpers only
3. [x] Per-endpoint `timeout`: passed to `build_request` as it is (see Decisions).
4. [x] `deprecated=`: a message string; both wrappers warn before anything else (see Decisions).
5. [ ] Argument validation: #136, shelved until after the 0.1.0 release (2026-11-17). The
   `validate_arguments=` option was removed until then, from `ClientX`, `AsyncClientX`, the verb
   decorators and `Endpoint`; adding it back is backward compatible. Planned: off by default; one `TypeAdapter` per parameter from its full annotation, so helper
   constraints such as `Query(ge=1)` apply; strict; only passed arguments; `ArgumentError` with the
   Pydantic error as its cause. Model instances aren't validated again (Pydantic's default).
6. [x] Exceptions (see Decisions): `ClientXError`, `DefinitionError`, `ArgumentError` (raised for path
   values; argument validation, item 5, will raise it too). A `*args` or `**kwargs` endpoint parameter
   raises `DefinitionError` in `Endpoint.__post_init__`. Later, maybe: wrap an unresolvable
   annotation's `NameError` with the endpoint's name
7. [x] Public exports in `clientx/__init__.py` (agreed 2026-11-17): the four bases, `__version__`, httpx2's
   `Auth`, `Request`, `Response` and `Timeout`, the helpers (`Url`, `Query`, `Header`, `Body`, `Form`,
   `File`, `Json`; `clientx.arguments` is no longer experimental), all three exceptions, and `method`.
   `get_argument_location` and `HttpxArgument` are internal now. Gone: `DumpConfig`,
   `DeprecatedMessage`, `PathParam` (now `Url`), and the `clientx.decoders` module.
8. [x] The client's `__repr__`, on `_BaseClientX`: class name, base URL and User-Agent, with a password in
   the base URL shown as `[redacted]` (the old one showed it).
9. [x] Logging: not ported (agreed 2026-11-17). Users rely on httpx2's own logging (the `httpx2` logger)
   and `event_hooks=`. A `clientx` logger is a question for later: #137.
10. [x] Decorator typing. The verb decorator is overloaded: without `decoder=` it returns
    `EndpointDecorator`, with one `DecodedEndpointDecorator[D]` (the endpoint must return what the decoder
    does). Both limit each overload to its kind of class, so a `def` endpoint on an `AsyncClientX` or
    `AsyncResource` is rejected by pyright and mypy. An `async def` endpoint on a sync class can't be: to a
    type checker it's a `def` returning a coroutine. The check when the class is defined catches it.
11. [ ] `clientx.tools` (old 314 lines) and `clientx.mcp` (old 210 lines): sidelined until after the
    0.1.0 release (2026-11-17), with the `mcp` extra removed. #138 has the findings and the preferred
    design.

Decoder decisions (agreed 2026-11-17):
- No `key=` unwrapping (old `TypeAdapterDecoder(key=...)`): for a wrapped body such as
  `{"count": 2, "results": [...]}`, return a model of the wrapper, or pass a `decoder=`. Can be
  added later as a decorator option if it's missed.
- [x] A `stream=True` decorator option: with `-> Response`, the endpoint returns the open, unread
  response, which the caller reads and closes (replaces `StreamResponseDecoder`). Only with
  `-> Response` and without a `decoder=`; anything else raises `DefinitionError`. `-> Iterator[...]`
  keeps streaming and closing by itself.
- `decoder=` stays (agreed 2026-11-17): typed streams such as SSE or NDJSON events
  (`-> Iterator[Event]` with a generator decoder) need it. To make it safe:
  - [x] `DefinitionError` when the class is defined for a decoder with `-> None`, an `async def`
    (coroutine) decoder, a generator decoder of the wrong kind (an async generator on a `def`
    endpoint, a plain one on an `async def` one), and a generator decoder on an endpoint that isn't
    annotated as a stream
  - [x] typing: type checkers check the decoder's return type against the annotation, for `def` and
    `async def` endpoints, pinned in `test_typing.py` (the decoder half of item 10). The verb decorator
    is overloaded; with `decoder=` it returns `DecodedEndpointDecorator[D]`, whose overloads are limited
    to each kind of class, so a decoded `async def` endpoint on a sync class is rejected too

## Tests

Rebuilt from scratch (agreed 2026-11-17); the old suite (25 files, 6,566 lines) is on `mainline`.

- Tests go through the public API, by feature: define a small client class, call it over
  `httpx2.MockTransport` (the `mock_transport` fixture), and check the request sent, the result or the
  error. Internals are tested directly only where that's simpler (`ParameterInfo`, path parsing).
- Conventions kept: `importlib` import mode, fixtures that return factories, anyio for async tests,
  and `test_typing.py` checked by pyright and mypy in `make typecheck`.
- Done: `conftest.py` (`mock_transport`), `test_public_api.py`, `test_typing.py`, `test_paths.py`,
  `test_query_and_headers.py`, `test_bodies.py`, `test_spreading.py`, `test_responses.py`, `test_clients.py`,
  `test_endpoints.py`, `test_signature.py`: the first wave (207 tests, 98% coverage).
  `test_bodies.py` covers #128 and #129.
- The coverage gate: `make test-ci`, which CI runs, fails below 95% (`--cov-fail-under=95`). It isn't
  in `[tool.coverage]`, so running one test file locally doesn't fail it.
- Later: tools and MCP get tests if they come back.
- Streaming tests need an iterator or async-generator `MockTransport` body: `bytes` bodies are read
  at once.

## Plan for what's left (agreed 2026-11-17)

1. [x] `CLAUDE.md`: rewritten from the code (`aeb4c41`).
2. [x] The code for 0.1.0 is done. AI support (item 11, #138) and argument validation (#136) wait until
   after the release, so the docs leave them out.
3. [x] Before the first page, add a test that type-checks every `python` code block in `docs/`,
   `README.md` and `llms.txt` with pyright, so snippets can't drift from the API again. Each block
   stands alone (its own imports); a deliberately incomplete one is fenced as `python no-check`. The
   test checks a list of rewritten files, which each page joins in the commit that rewrites it; once
   every page is rewritten, the list goes and every file is checked. Pages stay plain Markdown.
4. [x] Rewrite each page from the code, one per commit, using the old page only as a checklist of what to
   cover (docs review, 2026-11-17):
   1. `endpoints.md`: rewrite. Decorator options (`stream=`, `decoder=` as any callable,
      `deprecated=` as a string, `timeout=None` means no timeout), the required return annotation,
      mypy's `empty-body`, the `DeprecationWarning` note from `logging.md`, and "Endpoint names" moved
      from `resources.md` (a client reserves all of httpx2's names; a resource doesn't). `api.get(url)`
      works for an ad-hoc request, since `ClientX` is an `httpx2.Client`.
   2. `requests.md`: rewrite, following `_request.py`'s rules. No special parameter names; `Body()`
      is raw content and `Json()` is JSON; keys are `alias=`; `Url()` replaces `PathParam`; spreading
      only with `Query()`, `Header()` or `Form()`. A short "Not supported yet" note links #135 (no
      `exclude_unset`, no explicit `null`, defaults always sent).
   3. `responses.md`: new, replaces `decoders.md`. The return-annotation table, `-> Response` and
      `-> None`, streaming with `Iterator`/`AsyncIterator`, `stream=True`, custom `decoder=` functions
      (generators stream), how type checkers check them, and "Raising errors for 4xx and 5xx responses"
      moved from `configuration.md`.
   4. `resources.md`: update. New decoding in the examples, `DefinitionError` for unmounted resources
      and endpoints in two classes, no `base_url=` class argument.
   5. `configuration.md`: update. `base_url` is required and `user_agent=` is the only class argument;
      every httpx2 option works; authentication and closing stay; event hooks and the `httpx2` logger
      note come from `logging.md`; validation goes; a one-line pointer to the 4xx/5xx section.
   6. `async.md`: update. Annotation streaming in the examples; the AI section goes.
   7. `testing.md`: update. New examples; the tools and MCP part goes.
   8. `errors.md`: rewrite. `ClientXError`, `DefinitionError` and `ArgumentError`, when each is raised,
      and httpx2's errors.

   `decoders.md`, `logging.md` and `ai-tools.md` are deleted. A "Documenting your client" page
   (mkdocstrings settings) waits until after the release.
5. [x] Then `docs/README.md` and `README.md` (a simpler quickstart; no AI, `clientx[mcp]` or "pluggable
   decoders"), then `llms.txt`, then `CHANGELOG.md`: ClientX was never released, so the
   `[Unreleased]` section ("First public release") is rewritten to describe the new API rather than
   given a breaking-change entry.

Done on 2026-11-17, one commit per page, for review: the snippet test (`test/test_docs.py`) now
checks every Markdown file in `docs/`, `README.md` and `llms.txt`.

## Follow-ups for docs

- mkdocs (mkdocstrings, griffe) reads an endpoint from its source fine: signature, docstring and
  `Args:`. It doesn't show the HTTP method, path or `deprecated=` (they're in the decorator), and
  shows `Annotated[...]` in full unless `unwrap_annotated: true`. Imported instead of read from source,
  annotations collapse to `Annotated` and a mounted resource looks like a function (a descriptor with
  `__get__` only). Ideas: a "Documenting your client" page with the right mkdocstrings settings, and
  later a griffe extension that shows each endpoint's method and path.

`examples/` was dropped on 2026-11-17: the user wasn't a fan of what the examples demonstrated, and
they called live APIs, so CI could only lint and type-check them. Ideas if examples come back: tested
docs snippets, where every code sample in `docs/` is a file that CI type-checks and runs against a
mock transport (as FastAPI's `docs_src/` does), or one realistic client, such as for GitHub's REST
API, with a test that runs it against a mock transport.

## Trying it

`scratch/decoding_demo.py` (local only, not committed) runs the decoding prototype against a mock
transport: `uv run python scratch/decoding_demo.py`.
