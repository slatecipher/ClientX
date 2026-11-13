# ClientX guide

One page per topic. Start with the [README](../README.md) for an overview, install, and a quickstart.

- [Defining endpoints](endpoints.md): the verb decorators and their options, empty method bodies and mypy, and deprecating endpoints.
- [Resources](resources.md): grouping endpoints under a path prefix, nesting them, and plain methods for logic such as pagination.
- [Return types and decoders](decoders.md): `ModelDecoder`, `TypeAdapterDecoder`, `FromResponseDecoder`, the simple decoders, your own, and streaming.
- [Building requests](requests.md): how parameters become the path, query string, headers, form fields, JSON body, and files.
- [Client configuration](configuration.md): creating and closing a client, class defaults for the base URL and `User-Agent`, authentication, errors for 4xx and 5xx responses, and argument validation.
- [Async clients](async.md): `AsyncClientX` and `AsyncResource` for `async def` endpoints, concurrent requests, async streaming, and testing.
- [Logging](logging.md): ClientX's debug records, and your own request logging.
- [AI tools and MCP](ai-tools.md): endpoints as AI tools, serving a client over MCP, and listing a client's endpoints.
- [Testing](testing.md): testing a client, its tools, and an MCP server without the network.
- [Errors](errors.md): the errors ClientX raises, and when.
