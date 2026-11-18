# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0, the public API may change between minor versions.

## [Unreleased]

First public release.

### Added

- Declarative endpoints: subclass `ClientX` and decorate methods with `get`, `post`, `put`, `patch`, `delete`, `head` or `options` from `clientx.method`, as in `@method.get("/users/{user_id}")`. Endpoint bodies never run. The path defaults to `""`, so `@method.get()` calls the base URL, or on a resource, its prefix.
- Responses decoded from the return annotation: `-> None` returns nothing, `-> Response` the response, `-> str` and `-> bytes` the body, `-> Iterator[str]` and `-> Iterator[bytes]` stream it, and any other type is validated from the JSON body by Pydantic, `Annotated` constraints included. `decoder=` takes any function in place of that, and a generator decoder streams. `stream=True` returns the open, unread response. Type checkers check a decoder's return type against the endpoint's annotation.
- Request building as FastAPI decides where values come from, in reverse: a parameter named like a path placeholder fills it, a parameter with a helper (`Url`, `Query`, `Header`, `Json`, `Body`, `Form` or `File`) goes where the helper says, and any other parameter goes to the JSON body if it's a model, mapping, collection or dataclass, and to the query string otherwise. The helpers are built on `pydantic.Field`, with `alias=` as the name a value is sent under. A lone JSON parameter is the whole body, and several are the fields of a JSON object. A request has one kind of body: JSON, raw content, or a form, multipart with files. `None` values are left out.
- A model, dataclass or mapping marked `Query()`, `Header()` or `Form()` is spread into that part, one value per field.
- Path values are converted to text and percent-encoded, so a value can't add path segments, a query string or a fragment, or move up the path with `..`. `{name:path}` keeps slashes for values such as file paths. A `None` or empty path value, or a `{name:path}` value with an empty segment, raises `ArgumentError` before anything is sent, instead of calling a different path.
- Endpoints are checked when the class is defined, not on their first call: a missing return annotation, a type ClientX can't decode, a placeholder that names no parameter, a misplaced helper, a value that can't go to its part, or two kinds of body raise `DefinitionError`, with a message that names the fix. Annotations are evaluated then, so endpoints work in modules with `from __future__ import annotations`, and each endpoint's request is planned once rather than on every call.
- Errors for failed requests: a 4xx or 5xx response raises `httpx2.HTTPStatusError` from any endpoint, with the body already read and before anything is decoded. Turn it off with `raise_for_status=False` on the client, or set it per endpoint.
- Endpoint options: per-endpoint timeouts (`None` turns the timeout off), and deprecation warnings with a message, `deprecated="Use get_user() instead."`.
- Resources: group endpoints into `Resource` classes with a shared path prefix, and mount them on a client (or nest them) to call them as `client.users.retrieve(...)` through the client's connection. An endpoint can have a second name in its class; putting it in another class raises `DefinitionError`, since a resource's prefix would change its path.
- Clients: a `ClientX` is an `httpx2.Client`, created with a base URL and any `httpx2.Client` option, and closed at the end of a `with` block or with `close()`. A client class can set its `User-Agent` as a class argument, `class ExampleAPI(ClientX, user_agent="example-api/1.0")`. A client's `repr` hides any password in its base URL. Endpoints on a client can't use httpx2's names, such as `get` or `send`; endpoints on a resource can.
- Async clients: subclass `AsyncClientX`, an `httpx2.AsyncClient`, and write endpoints as `async def` methods with the same decorators, then `await` them. `AsyncResource` groups `async def` endpoints the way `Resource` groups `def` ones, and `-> AsyncIterator[str]` streams. Type checkers reject a `def` endpoint on an async client or resource, and ClientX rejects either kind on the other kind of class when it's defined.
- Exceptions: `DefinitionError`, a `TypeError`, and `ArgumentError`, a `ValueError` with the `parameter` it's about, both derived from `ClientXError`.
- `llms.txt`: a compact guide to ClientX's patterns and pitfalls for AI coding assistants.
- Support for Python 3.12, 3.13 and 3.14, with inline type information (`py.typed`).
