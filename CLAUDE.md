# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClientX is a library for typed, declarative HTTP API clients on Python 3.12+. Subclasses of `ClientX` declare endpoints as decorated methods with empty bodies. The decorator reads the method's signature and annotations and builds an `httpx2` request from them. It depends on `httpx2`, which is a separate package from `httpx`, and on `pydantic` v2.

## Commands

All tooling runs through `uv`:

```bash
uv sync --all-groups --reinstall-package clientx   # install/refresh deps + the package
make lint             # ruff format + ruff check --fix on src, test and examples
make lint-ci          # check-only variant used in CI
make typecheck        # pyright src + test/test_typing.py + examples (gates CI)
make typecheck-tests  # pyright test (advisory only in CI, never blocks)
make test             # pytest (coverage flags come from pyproject addopts)
make check            # lint + typecheck + test

uv run pytest test/test_request_factory.py                  # single file
uv run pytest test/test_clientx.py::test_name               # single test
uv run pytest -k "deprecat" --no-cov                        # by keyword, skip coverage
```

- `uv_build` installs the package as a regular wheel, not in editable mode, and `clientx.__version__` is read from installed metadata (`importlib.metadata`). If changes to `src/` don't show up, or imports fail, rerun `uv sync` with `--reinstall-package clientx`.
- Ruff uses a 120-character line length and preview mode with a broad rule set: `S` (bandit), `B`, `N`, `C90`, `BLE`, `UP` and others. `S101`/`S105` are ignored in `test/`.
- Pyright checks `src` in **strict** mode (`strict = ["src"]`) and tests in `standard` mode. New code in `src` needs complete annotations. Empty containers need explicit types (`parts: list[dict[str, Any]] = []`), and dataclass default factories need explicit types (`field(default_factory=dict[str, Any])`). Running `pyright src` on the command line overrides the wider `include` list in `pyproject.toml`.
- `test/test_typing.py` checks that decorated endpoints keep their signatures for type checkers. It uses `assert_type`, plus `# pyright: ignore` comments for calls that must be rejected (an unused ignore is an error there). Pyright normally hides an untyped decorator by falling back to the undecorated signature, so that file enables `reportUntypedFunctionDecorator`. The fallback would hide regressions that mypy users see as `Any`.

## Architecture

The public API is `clientx/__init__.py`, which also re-exports `httpx2.Response` and related types, plus the `clientx.methods`, `clientx.decoders` and `clientx.exceptions` modules. Modules whose names start with `_` are internal.

**Decoration time** (`_decorators.py`, `ApiMethod.__call__`): each verb decorator does the following:
1. Builds an `Endpoint` (`_endpoint_context.py`) that holds the method, a `URLPath` template, the decoder, the deprecation hook, tags and the timeout. `Endpoint.stream` is derived from the decoder: `StreamDecoder` subclasses and `StreamResponseDecoder` stream; there is no `stream=` option.
2. Sets `endpoint.func = wrapper`. The `func` setter captures the signature, resolves the return type with `get_type_hints`, and validates the decoder. As a result, `MissingReturnTypeError` and `MissingDecoderError` are raised **when the class is defined**, not when the method is called.
3. Records `wrapper -> endpoint` in `_registry.py` (so classes can find their endpoints) and appends the endpoint to `EndpointRegister.registry`, a process-wide `ClassVar` list. `test/conftest.py` has an autouse fixture that resets this list for every test, so tests that define client classes stay isolated.

**Class creation** (`_client.py`, `__init_subclass__`):
- `ClientX` and `Resource` subclasses reject endpoints and mounted resources whose names the base class already uses (`EndpointNameConflictError`; reserved names are `dir(base)` plus its annotations). Keep both bases' surfaces small, since every attribute is a name endpoints can't use: that's why sending is the module function `send_request()`, not a method, and why `Resource` keeps its state in `__clientx_*__` dunders.
- `Resource` subclasses (`prefix=`, `tags=` class arguments; inherited when omitted) join the prefix onto the path of each endpoint defined in the class body and prepend their tags. Prefixes are absolute, not composed through nesting.
- A `Resource` instance mounted as a class attribute is a descriptor: instance access returns a copy bound to the client (or parent resource) via `__clientx_parent__`; class access returns the unbound resource.

**Call time** (the `wrapper` inside the decorator):
1. `client_of(self)` walks resource parents to the `ClientX` instance (`UnboundResourceError` if a resource isn't mounted), then `endpoint.check_deprecation()`.
2. `endpoint.bind(self, args, kwargs)` returns `inspect.BoundArguments`.
3. `RequestFactory` (`_request_factory.py`) consumes the arguments through an `ArgumentCursor`. Each argument can be consumed only once, and any argument left over is an error. It does this in two passes:
   - Path placeholders `{name}` are consumed first and rendered.
   - Each remaining parameter is mapped to a request part, in this priority order: (a) the parameter name is itself a request part (`params`, `json`, `headers`, `data`, `files`); (b) a request-part helper in `Annotated` metadata: `Query(key)`, `Header(key)`, `Form(key)`, `Body()`, `File()`. They subclass the internal `Part`, which `AnnotationInfo.part` finds with `isinstance`, and each sets the class constant `request_part` (a `ClassVar`, not a dataclass field): a `RequestPartName` literal, which is also the httpx2 argument name. `Part` and the part names aren't public; users choose a part only by choosing a helper; (c) the value is a Pydantic model, which `ModelExtractor` expands field by field. Unannotated model fields go to JSON. Anything else raises `UnconsumableArgumentError`.
   - Models are dumped by `dump_model()`: `mode="json"` and `by_alias=True`, with any `DumpConfig` on top. So `AnnotationExtractor.from_base_model` maps serialization aliases too. Single keyed values go through `pydantic_core.to_jsonable_python`.
   - In `params`, `headers` and `data`, a value that isn't a mapping or a model is one named value. It goes under `Part.key`, or else under the parameter name or the dumped field name, with hyphens for headers (`_default_name`). This applies to parameters and to model fields. A parameter named after a part is always the whole part, as given.
   - The resulting part dicts are merged into copies (a caller's dict is never changed): dict values are shallow-merged and later parts win. `None` values are dropped from `params`, `headers` and `data`, because httpx2 would send them as empty values or reject them as headers; `json` keeps `null`. Numbers and booleans in headers become JSON text (`2`, `true`). The result is a `RequestSpec(path, parts)`.
4. `send_request()` (`_client.py`) builds and sends the request on the wrapped `httpx2.Client`. Then, unless the endpoint's `raise_for_status` (or else the client's `__clientx_raise_for_status__`, default `True`) is off, a 4xx or 5xx response raises `httpx2.HTTPStatusError` (`_raise_for_status` in `_decorators.py`). It reads and closes the response first, so the error keeps its body and a streamed response frees its connection; for a response that isn't streamed, httpx2 already did both. It's a check in the call path, not an httpx2 event hook, so user hooks and ad-hoc `client.client` requests are untouched. The wrapper times the call and logs one DEBUG record on the `clientx` logger (`_logging.py`) after the response or the failure (which it re-raises). The record has fixed `clientx_*` attributes and must never include values (header values, bodies, query strings); `test/test_logging.py` checks this.
5. If a decoder was given, it runs on any response that wasn't rejected above, and its output is returned (`_decode` in `_decorators.py`). A `StreamDecoder`'s iterator is wrapped so the response closes when iteration ends; a `StreamResponseDecoder` hands the open response to the caller. Without a decoder, `None` returns nothing and `Response` returns the raw (already read) response.

`_annotation_extractor.py` normalizes `Annotated` metadata from function signatures and from Pydantic `FieldInfo`/computed fields, including aliases, into `AnnotationInfo`/`NamedAnnotation`. It expands PEP 695 `type` aliases, plain and generic (`_unwrap_type_alias`), and puts the metadata of nested `Annotated` first, the way Python flattens it. A marker inside a union such as `X | None` isn't seen. Both the signature path and the model path use it.

`ClientX.__init__` forwards `**kwargs` to `httpx2.Client`. They are typed by the `HttpxClientKwargs` TypedDict in `_client_types.py`. `user_agent` is a property that writes the `User-Agent` header.

`tools.py` (public, `clientx.tools`) turns a client's endpoints into AI tools: it walks the client's class (and mounted resources) with `_registry.endpoint_for`, builds an argument model per endpoint (internal field names with parameter-name aliases, so `json` can't clash with `BaseModel`), and serializes results to JSON-friendly values. It must stay free of AI-SDK dependencies; protocol adapters build on it.

`mcp.py` (public, `clientx.mcp`, needs the `mcp` extra; `mcp` is also in the dev group so CI tests it) serves `list_tools()` over MCP with the SDK's low-level `Server`, using the core's schemas as-is (one source of truth). Non-object output schemas are wrapped as `{"result": ...}` with `$defs` moved to the top. Tests talk to it in-process with `mcp.Client(server)`.

`examples/beeceptor/` and `examples/jsonplaceholder/` contain complete example clients, run by the `examples/*_example.py` scripts. Both call live public APIs, so the scripts need network access; lint and typecheck cover them, but the test suite doesn't run them.

`llms.txt` (repo root) is a compact guide for AI coding assistants. Keep it in sync with the public API and README; its code sample must run and type-check.

## Conventions and releasing

`CONTRIBUTING.md` is the source of truth for commit messages, branch names, pull request descriptions, labels, and the release steps. Follow it for every commit and pull request.
