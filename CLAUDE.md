# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClientX turns typed method declarations into HTTP API clients, the way FastAPI turns them into server endpoints. A subclass of `ClientX` declares each endpoint as a method with an empty body and a verb decorator (`@method.get("/users/{user_id}")`). ClientX reads the signature once, then builds and sends an `httpx2` request on each call. Python 3.12+, on [httpx2](https://github.com/pydantic/httpx2) and [Pydantic v2](https://github.com/pydantic/pydantic). Pre-1.0.

## Commands

```bash
uv sync --all-groups --reinstall-package clientx   # install; rerun after changing pyproject.toml (the version comes from metadata)
make check            # lint + typecheck + test
make lint             # ruff format + ruff check --fix on src and test
make typecheck        # pyright on src (strict) and test/test_typing.py, then mypy on test/test_typing.py; gates CI
make typecheck-tests  # pyright on test/; advisory in CI
make test-ci          # pytest with the 95% coverage gate CI uses (make test: without the gate)
uv run pytest test/test_paths.py                       # one file
uv run pytest test/test_paths.py::test_name --no-cov   # one test, without coverage
```

- Ruff wraps code at 120 columns, and docstrings and comments at 80 (W505). `make lint` doesn't fix W505: rewrap by hand.
- Pyright is strict on `src`: complete annotations, and explicit types on empty containers and dataclass default factories.
- CI runs the tests on Python 3.12 to 3.14, and on the lowest dependency versions `pyproject.toml` allows.

## Architecture

An endpoint goes through three stages. Every check that can run before a call runs in the first two, so a mistake raises `DefinitionError` when its module is imported. Don't add call-time work that could be done there.

- **Decoration** (`_method.py`): each verb in `clientx.method` is a `Method`. Its decorator calls `inspect_signature` (`_signature.py`) and builds an `Endpoint` (`_endpoint.py`), whose `__post_init__` checks the parameters, return annotation, `stream=` and `decoder=`, and picks the decoder (`_decoding.py`). It returns a sync or an async wrapper, by the method's kind, and registers wrapper → endpoint in `_registry.py`.
- **Class creation** (`_client.py`, `_class_setup.py`): `__init_subclass__` on `ClientX`, `AsyncClientX`, `Resource` and `AsyncResource` checks the class body, claims its endpoints (an endpoint has one owner class), joins a resource's prefix and tags onto them, then calls `Endpoint.set_up_request()`, which builds the endpoint's `RequestPlan` (`_request.py`) now that its path is final.
- **Call** (the wrappers in `_method.py`): deprecation warning → `client_of` (walks resource parents up to the client) → `Endpoint.bind` → `RequestPlan.build` (the URL path and `build_request` arguments) → `build_request` and `send` on the client itself → `httpx2.HTTPStatusError` for a 4xx or 5xx unless `raise_for_status` is off → the open response for `stream=True`, or else `decode` / `adecode`.

Where the rules are written down:

- `_request.py`'s module docstring: where each parameter goes (a path placeholder, its helper's part, or else inferred: models, mappings, collections and dataclasses to JSON, plain values to the query), the keys it's sent under, `None` left out, one kind of body, spreading a model marked `Query()`, `Header()` or `Form()`, and path encoding.
- `_decoding.py`'s module docstring: how the return annotation decides decoding (`-> None`, `Response`, `str`, `bytes`, `Iterator[str]` or `Iterator[bytes]`, anything else through a `TypeAdapter`).
- `_signature.py`: one `ParameterInfo` per parameter, with `Annotated` kept and PEP 695 `type` aliases expanded. A parameter's helper is the last `clientx.arguments` mark in its outermost `Annotated`. The helpers wrap `pydantic.Field` and append their `HttpxArgument` to its metadata (`_arguments.py`).
- `_types.py`: shared types: `HttpxArgument`, `Send`, the type aliases, and TypedDicts that mirror httpx2's signatures (`HttpxClientOptions`, `AsyncHttpxClientOptions`, `BuildRequestKwargs`); a test in `test_clients.py` fails when httpx2's parameters change. It's the only module that imports httpx2's private modules.

Rules that span modules:

- `ClientX` is an `httpx2.Client`, and `AsyncClientX` an `httpx2.AsyncClient`. An endpoint or mounted resource can't reuse a name the base class has, which includes all of httpx2's (`get`, `send`, `headers`...), so ClientX keeps its own state in `__clientx_*__` dunders. Those names are free on a resource.
- `def` endpoints go on `ClientX` and `Resource`, `async def` endpoints on `AsyncClientX` and `AsyncResource`, and a resource mounts only on its own kind. A mounted resource is a descriptor that returns a copy bound to its parent. Prefixes are absolute: they don't add up through nesting.
- The decorator protocols in `_method.py` limit each overload to one kind of class, so only one can match even with `Any` (if two matched, mypy would treat the endpoint as untyped), and repeat the `def` overload last, so both checkers' errors name it. Type checkers can't reject an `async def` endpoint on a sync class; the check at class creation does.
- ClientX percent-encodes path values, `.` and `..` segments included. Never pre-encode them in tests or docs.

## Tests

- Tests go through the public API, one file per feature (`test_paths.py`, `test_query_and_headers.py`, `test_bodies.py`, `test_spreading.py`, `test_responses.py`, `test_clients.py`, `test_endpoints.py`); internals are tested directly only where that's simpler (`test_signature.py`).
- pytest runs in strict mode and `importlib` import mode, so test modules can't import each other: shared helpers are fixtures in `conftest.py`. Send requests through `mock_transport(sent=None, handler=None, *, status=200, **response)`, which records each request in `sent` and serves async clients too. Async tests use anyio (`@pytest.mark.anyio`). A streamed response body must be an iterator: a `bytes` body is read at once.
- `test/test_typing.py` is the static typing contract, checked by pyright and mypy in `make typecheck`, on its own, so it keeps its own transport instead of the fixtures. It uses `assert_type`, and each line that must be rejected has one comment per checker: `# type: ignore[code]  # pyright: ignore[rule]`. Pyright ignores `# type: ignore` (`enableTypeIgnoreComments = false`), so elsewhere in `test/` suppress it with `# pyright: ignore[rule]`.

## Docs

- `README.md` is the PyPI page: short, with absolute GitHub links into the guide in `docs/`, whose pages link to each other relatively. `llms.txt` is a compact guide for AI assistants and must match the docs and the API.
- Snippets use `from clientx import method` and `@method.get(...)`, put `clientx` imports in the third-party block next to `httpx2` and `pydantic`, and send credentials only through httpx2's `auth=`. Link to httpx2's docs rather than restating them.

## Conventions and releasing

@CONTRIBUTING.md is the source of truth for commit messages, branch names, pull request descriptions, labels, docstrings, and the release steps. Follow it for every commit and pull request, and its Docstrings section for every docstring you write or change. Keep this section, and the `@CONTRIBUTING.md` import in it, when rewriting this file.
