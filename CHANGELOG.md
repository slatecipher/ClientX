# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0, the public API may change between minor versions.

## [Unreleased]

First public release.

### Added

- Declarative endpoints: subclass `ClientX` and decorate methods with `get`, `post`, `put`, `patch`, `delete`, `head` or `options`. Path templates such as `/users/{user_id}` are filled from method arguments.
- Request building from parameter names (`params`, `json`, `headers`, `data`, `files`), from `Annotated[..., FieldX(...)]` metadata, and from Pydantic models, with `DumpConfig` to control serialization. `None` values are left out of query parameters, headers and form fields, so optional parameters and filter models can default to `None`. JSON bodies keep `null`.
- Typed responses. Type checkers verify that each method's return annotation matches its decoder. Built-in decoders: `ModelDecoder`, `TypeAdapterDecoder`, `FromResponseDecoder`, `json_decoder`, `text_decoder` and `content_decoder`.
- Streaming with `StreamLinesDecoder`, `StreamChunksDecoder` and custom `StreamDecoder` subclasses. ClientX releases the connection when iteration ends. `StreamResponseDecoder` returns the open streamed response, which the caller reads to the end or closes.
- Endpoint metadata: an `EndpointRegister` of `Endpoint` objects for tooling, tags, per-endpoint timeouts, and deprecation warnings with `DeprecatedMessage`.
- Resources: group endpoints into `Resource` classes with a shared path prefix and tags, and mount them on a client (or nest them) to call them as `client.users.retrieve(...)` through the client's connection.
- A `ClientXError` base class for all ClientX exceptions.
- Structured debug logging: one `DEBUG` record per endpoint call on the `clientx` logger, with `clientx_*` attributes for the endpoint, method, path, request parts, status, elapsed time, and error. Values such as header values, bodies, and query strings are never logged.
- Support for Python 3.12, 3.13 and 3.14, with inline type information (`py.typed`).
