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
- Errors are plain `TypeError` for now, with the old messages, until the exceptions module returns.

## Done

| Module | What it does now |
|---|---|
| `_client.py` | `ClientX`, `AsyncClientX`, `Resource`, `AsyncResource`; `_configure`; `client_of(owner, kind)`; each base's `__clientx_is_async__` flag; `_BaseResource.__set_name__` |
| `_class_setup.py` | `set_up_client`, `set_up_resource`: one-kind check, reserved-name check, endpoint-kind check, claiming endpoints (`owner`), resource prefix and tags; `check_mount` |
| `_registry.py` | `register_endpoint_function`, `endpoint_for` (stores `(wrapper, endpoint)` pairs) |
| `_endpoint.py` | `Endpoint` dataclass; `__post_init__` checks the first parameter and the return annotation, sets `stream`, resolves `decoder`; `bind`, `parameters()` |
| `_signature.py` | `inspect_signature`, `SignatureInfo`, `ParameterInfo`, `ReturnInfo`; expands PEP 695 `type` aliases; unresolvable hints raise |
| `_decoding.py` | `is_stream`, `default_decoder`, `decode`/`adecode` (stream closing), `raise_status_error`/`araise_status_error` |
| `_method.py` | the verb decorator and the sync/async wrappers: bind, send (`stream=`), raise for 4xx/5xx, decode |
| `_types.py`, `arguments.py`, `_arguments.py` | option TypedDicts, shared aliases; the `Field`-based request-part helpers |

## Missing functionality (besides docs and tests)

Suggested order:

1. [x] `src/clientx/py.typed`: back in place, and the built wheel includes it. (The wheel also
   includes `clientx/pre/`: delete it before any release.)
2. [ ] Request building (old `_request_factory.py` + `_annotation_extractor.py`, ~650 lines). The
   wrappers send `build_request(endpoint.method, "")` and ignore `arguments`. Needs a design talk first:
   - path templates (`{name}`, `{name:path}`, `{{ }}`), encoding, `PathValueError`; class-definition
     checks for unknown placeholders (rerun after a resource prefix) and bad converters
   - mapping parameters to request parts with the new helpers (`Url`, `Query`, `Header`, `Cookie`,
     `Body` = raw content, `Form`, `File`, `Json`); parameters named after a part; model expansion;
     merge rules; dropping `None`; header value formatting; what a helper's `alias` means on a parameter
   - the one-helper, outermost-`Annotated` rule (old `MisplacedHelperError`); `DumpConfig`
3. [ ] Per-endpoint `timeout` (stored, never sent).
4. [ ] `deprecated=` (stored, never called) and the old public `DeprecatedMessage`.
5. [ ] Argument validation (`validate_arguments` is stored on endpoint and client, never read).
6. [ ] Exceptions module (`ClientXError` and subclasses; old ones also subclass `TypeError`/`ValueError`).
   `MissingDecoderError` is no longer needed.
7. [ ] Public exports in `clientx/__init__.py`: `AsyncClientX`, `Resource`, `AsyncResource`,
   `ClientXError`, `__version__`, httpx2 re-exports (`Auth`, `Request`, `Response`, `Timeout`),
   `DeprecatedMessage`, `DumpConfig`; decide whether to re-export the `clientx.arguments` helpers.
8. [ ] The client's `__repr__` (old: class name, base URL, User-Agent).
9. [ ] Logging (old `_logging.py`): one DEBUG record per call, never values.
10. [ ] Decorator typing (old `RawEndpointDecorator`/`DecodedEndpointDecorator` overloads): check a
    `decoder=` against the annotation; reject `async def` endpoints on sync classes for type checkers.
    `Method.__call__` has no return annotation yet.
11. [ ] `clientx.tools` (old 314 lines), then `clientx.mcp` (old 210 lines).

Open decoder decisions: `key=` unwrapping (old `TypeAdapterDecoder(key=...)`); a streamed open
response (old `StreamResponseDecoder`).

## Follow-ups for docs, tests and examples

- `llms.txt:92` and `docs/errors.md:7`: httpx2's names are reserved on clients, free on resources.
- `docs/decoders.md`: rewrite for annotation-driven decoding.
- Docs and `examples/` still use the `base_url=` class argument and the old decoder classes.
- Tests still import the old modules (`clientx.exceptions`, `clientx._client_types`, `clientx._compiler`, ...).
  Rename or move the tests that define `send`/`stream` endpoints on a `ClientX` (`test_decorators.py`).
  `test_unresolvable_hints_fall_back_to_the_raw_annotations` must expect a `NameError` now.
  Streaming tests need an iterator or async-generator `MockTransport` body: `bytes` bodies are read at once.

## Known lint items

- `_method.py`: unused `arguments` in both wrappers (until request building); trailing whitespace after
  the `Endpoint(...)` call.
- `_arguments.py`: ruff UP047 on `bind_argument`.

## Trying it

`scratch/decoding_demo.py` (local only, not committed) runs the decoding prototype against a mock
transport: `uv run python scratch/decoding_demo.py`.
