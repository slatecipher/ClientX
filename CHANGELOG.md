# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is below 1.0, the public API may change between minor versions.

## [Unreleased]

First public release.

### Added

- Declarative endpoints: subclass `ClientX` and decorate methods with `get`, `post`, `put`, `patch`, `delete`, `head` or `options`. Path templates such as `/users/{user_id}` are filled from method arguments.
- Request building from parameter names (`params`, `json`, `headers`, `data`, `files`), from request-part annotations such as `Annotated[int | None, Query("userId")]` (also through `type` aliases), and from Pydantic models, which are dumped in JSON mode and by alias unless `DumpConfig` says otherwise. A single query parameter, header or form value is sent under its `key`, or under its parameter or field name. `None` values are left out of query parameters, headers and form fields, so optional parameters and filter models can default to `None`. JSON bodies keep `null`.
- Request-part helpers: `Query`, `Header`, `Form`, `Body` and `File`, named like FastAPI's, send a parameter or model field to that part, with an optional `key` for query parameters, headers and form fields.
- Typed responses. Type checkers verify that each method's return annotation matches its decoder. Built-in decoders: `ModelDecoder`, `TypeAdapterDecoder`, `FromResponseDecoder`, `json_decoder`, `text_decoder` and `content_decoder`.
- Streaming with `StreamLinesDecoder`, `StreamChunksDecoder` and custom `StreamDecoder` subclasses. ClientX releases the connection when iteration ends. `StreamResponseDecoder` returns the open streamed response, which the caller reads to the end or closes.
- Endpoint metadata: an `EndpointRegister` of `Endpoint` objects for tooling, tags, per-endpoint timeouts, and deprecation warnings with `DeprecatedMessage`.
- Resources: group endpoints into `Resource` classes with a shared path prefix and tags, and mount them on a client (or nest them) to call them as `client.users.retrieve(...)` through the client's connection.
- AI tools: `clientx.tools.list_tools()` describes a client's endpoints, including those on resources, as tools with JSON Schemas for arguments and results and safety hints from the HTTP method. `Tool.call()` validates a model's arguments and runs the endpoint through the client.
- MCP adapter (the `mcp` extra): `clientx.mcp.run_mcp_server()` serves a client's endpoints as MCP tools over stdio, with method-based tool annotations, structured results, and errors returned as tool results. `create_mcp_server()` returns the server for other transports.
- `llms.txt`: a compact guide to ClientX's patterns and pitfalls for AI coding assistants.
- A `ClientXError` base class for all ClientX exceptions.
- Structured debug logging: one `DEBUG` record per endpoint call on the `clientx` logger, with `clientx_*` attributes for the endpoint, method, path, request parts, status, elapsed time, and error. Values such as header values, bodies, and query strings are never logged.
- Support for Python 3.12, 3.13 and 3.14, with inline type information (`py.typed`).
