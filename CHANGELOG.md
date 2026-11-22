# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0, the public API may change between minor versions.

## [Unreleased]

### Changed

- The `User-Agent` lists every product that's set, most significant first, instead of only the first: the app's, from `user_agent=` or a `User-Agent` in `headers=` when the client is created, then the class's `user_agent=` class argument, then `ClientX/<version>`. A package built on ClientX keeps its own product in the header when its users add theirs, so the API can still tell which package and version sent a request. A client with a `user_agent=` class argument now sends `ClientX/<version>` after it too. **Breaking:** a test or server that expects the exact `User-Agent` a client sent before sees a longer one. To send one exact `User-Agent`, set `client.headers["User-Agent"]` after creating the client.

## [0.2.1] - 2026-11-22

### Fixed

- An annotation that names a type that isn't defined yet, such as a model defined below the client class, raises `DefinitionError` naming the endpoint, with Python's `NameError` as its `__cause__`, instead of a bare `NameError` that didn't say which endpoint it was in.

## [0.2.0] - 2026-11-21

### Added

- Argument validation, off by default: a client created with `validate_arguments=True` checks each call's arguments against their annotations before anything is sent, strictly, as a type checker would, and with a helper's constraints, such as `Query(ge=1)`. An argument that doesn't fit raises `ArgumentError`, with Pydantic's `ValidationError` as its cause. Only the arguments a call passes are checked, the request is built from them unchanged, and a type Pydantic can't validate, such as a binary file, isn't checked.

## [0.1.0] - 2026-11-20

First public release.

### Added

- Declarative endpoints: subclass `ClientX` and decorate methods with `get`, `post`, `put`, `patch`, `delete`, `head` or `options` from `clientx.method`, as in `@method.get("/users/{user_id}")`. Endpoint bodies never run. The path defaults to `""`, so `@method.get()` calls the base URL, or on a resource, its prefix.
- Responses decoded from the return annotation: `-> None` returns nothing, `-> Response` the response, `-> str` and `-> bytes` the body, `-> Iterator[str]` and `-> Iterator[bytes]` stream it, and any other type is validated from the JSON body by Pydantic, `Annotated` constraints included. `decoder=` takes any function in place of that, and a generator decoder streams. `stream=True` returns the open, unread response. Type checkers check a decoder's return type against the endpoint's annotation.
- Request building from the signature, never guessed: a parameter named like a path placeholder fills it, and every other parameter has a helper (`Url`, `Query`, `Header`, `Json`, `Body`, `Form` or `File`) that says where it goes. A parameter without one raises `DefinitionError`, with the helper it most likely needs in the message. The helpers are built on `pydantic.Field`, with `alias=` as the name a value is sent under. A lone JSON parameter that isn't a plain value is the whole body, and several are the fields of a JSON object. A request has one kind of body: JSON, raw content, or a form, multipart with files, where a list of files repeats the field. `None` values are left out, and so are empty lists, except that a JSON parameter passed `None` explicitly is sent as `null`. Path, query, header and form values are plain values from an allow-list (`str`, `int`, `float`, `bool`, `Enum`, `date`, `datetime`, `time`, `UUID`, `Decimal`, `bytes`, a `Literal` of those, or a `NewType` of one), each with one text form, and `Any` is the escape hatch. A JSON value Pydantic can't serialize or that holds NaN or infinity raises `ArgumentError` before anything is sent, and so does a header name or value that isn't ASCII, or `DefinitionError` for a name known when the class is defined.
- A model, dataclass or mapping marked `Query()`, `Header()` or `Form()` is spread into that part, one value per field.
- `Send`, next to a helper, changes how a parameter is sent. `Send(embed=True)` sends a lone JSON parameter under its name, as FastAPI's `Body(embed=True)` does, so `ids: Annotated[list[str], Json(), Send(embed=True)]` sends `{"ids": [...]}` instead of the list as the whole body. `Send(exclude_unset=True)`, `Send(exclude_none=True)` and `Send(exclude_defaults=True)` apply Pydantic's dump options to a JSON value or a spread model, such as sending only the fields that were set for a PATCH, and raise `DefinitionError` where they'd have nothing to act on, which Pydantic would ignore silently. `Send(exclude_unset=True)` also leaves out a parameter the caller didn't pass, so the server's default applies instead of the signature's. `Send(json_part=True)` sends a `Form()` parameter's value as a JSON part of a multipart form, as some APIs take next to files.
- Path values are converted to text and percent-encoded, so a value can't add path segments, a query string or a fragment, or move up the path with `..`. `{name:path}` keeps slashes for values such as file paths. A `None` or empty path value, or a `{name:path}` value with an empty segment, raises `ArgumentError` before anything is sent, instead of calling a different path.
- Endpoints are checked when the class is defined, not on their first call: a missing return annotation, a type ClientX can't decode, a placeholder that names no parameter, a brace that isn't part of a placeholder, a path parameter that can be `None`, a parameter without a helper, a misplaced helper, a value that can't go to its part (a type that isn't a plain value, a `File()` that's a `str`, or a stream of the wrong kind for the client), two values sent under one key, or two kinds of body raise `DefinitionError`, with a message that names the fix. Annotations are evaluated then, so endpoints work in modules with `from __future__ import annotations`, and each endpoint's request is planned once rather than on every call.
- Errors for failed requests: a 4xx or 5xx response raises `httpx2.HTTPStatusError` from any endpoint, with the body already read and before anything is decoded. Turn it off with `raise_for_status=False` on the client, or set it per endpoint.
- Endpoint options: per-endpoint timeouts (`None` turns the timeout off), deprecation warnings with a message, `deprecated="Use get_user() instead."`, and tags. A resource's tags go before its endpoints' own, a resource subclass's tags are added to its parent's, and each tag is kept once. AI tools carry them, to choose which tools to give a model.
- Resources: group endpoints into `Resource` classes with a shared path prefix, and mount them on a client (or nest them) to call them as `client.users.retrieve(...)` through the client's connection. An endpoint can have a second name in its class; putting it in another class raises `DefinitionError`, since a resource's prefix would change its path.
- Clients: a `ClientX` is an `httpx2.Client`, created with a base URL and any `httpx2.Client` option, and closed at the end of a `with` block or with `close()`. A client class can set its base URL and `User-Agent` as class arguments, `class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-api/1.0")`, and a value given when creating a client wins. A base URL must be absolute, with a scheme and a host, or it raises when the class is defined or the client created, not on the first request. A client's `repr` hides any password in its base URL. Endpoints on a client can't use httpx2's names, such as `get` or `send`; endpoints on a resource can.
- Async clients: subclass `AsyncClientX`, an `httpx2.AsyncClient`, and write endpoints as `async def` methods with the same decorators, then `await` them. `AsyncResource` groups `async def` endpoints the way `Resource` groups `def` ones, and `-> AsyncIterator[str]` streams. Type checkers reject a `def` endpoint on an async client or resource, and ClientX rejects either kind on the other kind of class when it's defined.
- Exceptions: `DefinitionError`, a `TypeError`, and `ArgumentError`, a `ValueError` with the `parameter` it's about, both derived from `ClientXError`, as is the AI tools' `ToolError`.
- AI tools: `clientx.tools.list_tools(client)` describes each endpoint a model can use as a `Tool`, with a description from its docstring, a compact JSON Schema of its arguments, each described by its helper or its docstring's `Args:`, an output schema, hints from its HTTP method, and its tags. `Tool.call()` and `acall()` validate a model's arguments, call the endpoint and return JSON-ready data. A failed call raises `ToolError`, with a message written for the model that never holds the host or query string. It depends on no AI library.
- Documentation: a guide in `docs/`, one page per topic, whose code samples are tested, and an API reference page that lists every public name.
- `llms.txt`: a compact guide to ClientX's patterns and pitfalls for AI coding assistants.
- Support for Python 3.12, 3.13 and 3.14, with inline type information (`py.typed`).

[Unreleased]: https://github.com/slatecipher/ClientX/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/slatecipher/ClientX/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/slatecipher/ClientX/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/slatecipher/ClientX/releases/tag/v0.1.0
