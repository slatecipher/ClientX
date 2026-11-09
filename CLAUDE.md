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
3. Appends the endpoint to `EndpointRegister.registry`, a process-wide `ClassVar` list. `test/conftest.py` has an autouse fixture that resets this list for every test, so tests that define client classes stay isolated.

**Call time** (the `wrapper` inside the decorator):
1. `endpoint.check_deprecation()`.
2. `endpoint.bind(self, args, kwargs)` returns `inspect.BoundArguments`.
3. `RequestFactory` (`_request_factory.py`) consumes the arguments through an `ArgumentCursor`. Each argument can be consumed only once, and any argument left over is an error. It does this in two passes:
   - Path placeholders `{name}` are consumed first and rendered.
   - Each remaining parameter is mapped to a request part, in this priority order: (a) the parameter name is itself a `RequestPart` (`params`, `json`, `headers`, `data`, `files`); (b) `Annotated[..., FieldX(part, key=..., dump_config=...)]` metadata; (c) the value is a Pydantic model, which `ModelExtractor` expands field by field. Unannotated model fields go to JSON. Anything else raises `UnconsumableArgumentError`.
   - The resulting part dicts are merged: dict values are shallow-merged and later parts win. The result is a `RequestSpec(path, parts)`.
4. `ClientX.send()` builds and sends the request on the wrapped `httpx2.Client`.
5. If a decoder was given, it always runs and its output is returned (`_decode` in `_decorators.py`). A `StreamDecoder`'s iterator is wrapped so the response closes when iteration ends; a `StreamResponseDecoder` hands the open response to the caller. Without a decoder, `None` returns nothing and `Response` returns the raw (already read) response.

`_annotation_extractor.py` normalizes `Annotated` metadata from function signatures and from Pydantic `FieldInfo`/computed fields, including aliases, into `AnnotationInfo`/`NamedAnnotation`. Both the signature path and the model path use it.

`ClientX.__init__` forwards `**kwargs` to `httpx2.Client`. They are typed by the `HttpxClientKwargs` TypedDict in `_client_types.py`. `user_agent` is a property that writes the `User-Agent` header.

`examples/beeceptor/` contains a complete example client.

## Conventions and releasing

`CONTRIBUTING.md` is the source of truth for commit messages, branch names, pull request descriptions, labels, and the release steps. Follow it for every commit and pull request.
