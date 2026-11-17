# Client refactor: status

Branch `experiment/signature-info`, last updated 2026-11-16. A rewrite of `src/clientx` that's
simpler and easier to read. The old code is kept in `src/clientx/pre/` for reference while
pieces are ported one small step at a time. Delete this file and `pre/` when the port is done.

## Decisions so far

- `ClientX` and `AsyncClientX` subclass `httpx2.Client` and `httpx2.AsyncClient` (no wrapped
  `__clientx_client__`). Context managers, `close`, `send`, `build_request` come from httpx2.
- So httpx2's public names (`get`, `send`, `stream`, `headers`, ...) can't be endpoint names on a
  client. Accepted by design: those names are free on a `Resource`.
- `base_url` is a required `__init__` argument; the `base_url=` class argument is dropped for now.
  `user_agent=` is still a class argument.
- Each client has a real `__init__` (no `if TYPE_CHECKING` signatures). `HttpxClientOptions` holds
  only httpx2's options; `_configure()` applies `user_agent`, `raise_for_status`, `validate_arguments`.
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
  and `None` means no timeout. Unlike `raise_for_status=` and `validate_arguments=`, where `None` means
  the client's setting. The old code read `timeout=None` as the client's.
- Request building follows FastAPI's rules, run the other way (agreed 2026-11-17):
  - A parameter without a helper goes to the path if a placeholder names it; to the JSON body if it's
    a model, mapping, list or dataclass; otherwise to the query string. Decided when the class is defined.
  - A helper on a model parameter sends all its fields to that part. Helpers on model fields aren't
    supported (`DefinitionError`).
  - One JSON parameter is the whole body; several are keyed by parameter name.
  - With several helpers on one parameter, the last one wins. A helper nested inside another type,
    such as `Annotated[str, Header()] | None`, raises `DefinitionError`.

## Done

| Module | What it does now |
|---|---|
| `_client.py` | `ClientX`, `AsyncClientX`, `Resource`, `AsyncResource`; `_configure`; `client_of(owner, kind)`; each base's `__clientx_is_async__` flag; `_BaseResource.__set_name__` |
| `_class_setup.py` | `set_up_client`, `set_up_resource`: one-kind check, reserved-name check, endpoint-kind check, claiming endpoints (`owner`), resource prefix and tags, then each endpoint's `set_up_request()`; `check_mount` |
| `_registry.py` | `register_endpoint_function`, `endpoint_for` (stores `(wrapper, endpoint)` pairs) |
| `_endpoint.py` | `Endpoint` dataclass; `__post_init__` checks the first parameter and the return annotation, sets `stream`, resolves `decoder`; `bind`, `parameters()`; `request` (the `RequestPlan`), `set_up_request()`, `request_arguments()` (adds `timeout`) |
| `_signature.py` | `inspect_signature`, `SignatureInfo`, `ParameterInfo`, `ReturnInfo`; expands PEP 695 `type` aliases; unresolvable hints raise; a parameter's last helper wins |
| `_decoding.py` | `is_stream`, `default_decoder`, `decode`/`adecode` (stream closing), `raise_status_error`/`araise_status_error` |
| `_method.py` | the verb decorator and the sync/async wrappers: warn if deprecated, bind, build the request from `endpoint.request_arguments()` (path, `timeout`), send (`stream=`), raise for 4xx/5xx, decode |
| `_types.py`, `arguments.py`, `_arguments.py` | option TypedDicts, shared aliases; the `Field`-based request-part helpers |
| `exceptions.py` | `ClientXError`, `DefinitionError` (every check above raises it), `ArgumentError` (path values) |
| `_request.py` | `plan_request(template, parameters)` checks the path rules and returns a `RequestPlan` (the parsed path, for now); `RequestPlan.build(arguments)` renders the path. Path templates: `Placeholder`, `_parse_path` (`string.Formatter`; a bad template raises `DefinitionError`), `_render_path` (percent-encoding; a bad value raises `ArgumentError`) |

## Missing functionality (besides docs and tests)

Suggested order:

1. [x] `src/clientx/py.typed`: back in place, and the built wheel includes it. (The wheel also
   includes `clientx/pre/`: delete it before any release.)
2. [ ] Request building (old `_request_factory.py` + `_annotation_extractor.py`, ~650 lines). The
   wrappers send `build_request(endpoint.method, "")` and ignore `arguments`. Rules agreed (see
   Decisions). Build one plan per endpoint at class setup, after the resource prefix is joined. Steps:
   - [x] path templates (`{name}`, `{name:path}`, `{{ }}`), sent by the wrappers. Checked at class
     setup: each placeholder names a parameter; `Url()` needs a placeholder; a placeholder's parameter
     has no other helper. Left for the next step: path parameters must be plain values
   - query and headers: inference, the key sent (alias; `_` to `-` for headers), dropping `None`,
     header value formatting; `DefinitionError` for a helper nested inside another type
   - bodies (`json`, `content`, `data`, `files`). Open: an `embed` option for a lone JSON value;
     parameters named after a part; keeping `Cookie` (httpx2 is deprecating per-request cookies);
     rejecting `default=` inside a helper
   - models with a helper, spread into that part; `DumpConfig`. Drop the model-field examples from the
     `arguments.py` docstring.
3. [x] Per-endpoint `timeout`: passed to `build_request` as it is (see Decisions).
4. [x] `deprecated=`: a message string; both wrappers warn before anything else (see Decisions).
5. [ ] Argument validation (`validate_arguments` is stored on endpoint and client, never read).
6. [ ] Exceptions (see Decisions). Done: `ClientXError`, `DefinitionError`, `ArgumentError` (raised for
   path values; argument validation, item 5, will raise it too). Still to do:
   - reject `*args`/`**kwargs` endpoint parameters (old `EndpointSignatureError`; not ported yet)
   - later, maybe: wrap an unresolvable annotation's `NameError` with the endpoint's name
7. [ ] Public exports in `clientx/__init__.py`: `AsyncClientX`, `Resource`, `AsyncResource`,
   `ClientXError`, `__version__`, httpx2 re-exports (`Auth`, `Request`, `Response`, `Timeout`),
   `DumpConfig`; decide whether to re-export the `clientx.arguments` helpers.
8. [ ] The client's `__repr__` (old: class name, base URL, User-Agent).
9. [ ] Logging (old `_logging.py`): one DEBUG record per call, never values.
10. [ ] Decorator typing (old `RawEndpointDecorator`/`DecodedEndpointDecorator` overloads): check a
    `decoder=` against the annotation; reject `async def` endpoints on sync classes for type checkers.
    `Method.__call__` returns a plain generic decorator for now: pyright and mypy both keep the
    endpoint's signature, but accept any `decoder=` and either kind of endpoint on any class.
11. [ ] `clientx.tools` (old 314 lines), then `clientx.mcp` (old 210 lines).

Open decoder decisions: `key=` unwrapping (old `TypeAdapterDecoder(key=...)`); a streamed open
response (old `StreamResponseDecoder`).

## Follow-ups for docs, tests and examples

- `llms.txt:92` and `docs/errors.md:7`: httpx2's names are reserved on clients, free on resources.
- `docs/decoders.md`: rewrite for annotation-driven decoding.
- Docs and `examples/` still use the `base_url=` class argument and the old decoder classes.
- `DeprecatedMessage(...)` becomes a plain string in `docs/endpoints.md` (drop "any callable"),
  `llms.txt:78`, `examples/beeceptor/beeceptor_client.py`, and `test/test_async.py`, `test_tools.py`,
  `test_endpoint_context.py`, `test_public_api.py`. A test can check the warning names the caller's file.
- `docs/endpoints.md:31` and `llms.txt:78`: an endpoint's `timeout=None` now means no timeout; leaving
  it out uses the client's.
- `docs/errors.md`, `llms.txt:103` and the tests' `pytest.raises(...)`: the old exception classes become
  `DefinitionError` or `ArgumentError` (tests match on the message). `examples/jsonplaceholder_example.py`
  catches `ArgumentValidationError`.
- Tests still import the old modules (`clientx._client_types`, `clientx._compiler`, ...).
  Rename or move the tests that define `send`/`stream` endpoints on a `ClientX` (`test_decorators.py`).
  `test_unresolvable_hints_fall_back_to_the_raw_annotations` must expect a `NameError` now.
  Streaming tests need an iterator or async-generator `MockTransport` body: `bytes` bodies are read at once.

## Known lint items

- `_arguments.py`: ruff UP047 on `bind_argument`.

## Trying it

`scratch/decoding_demo.py` (local only, not committed) runs the decoding prototype against a mock
transport: `uv run python scratch/decoding_demo.py`.
