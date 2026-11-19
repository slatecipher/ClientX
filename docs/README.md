# ClientX guide

One page per topic. Start with the [README](../README.md) for an overview, install, and a quickstart.

- [Defining endpoints](endpoints.md): the verb decorators and their options, the rules for an endpoint method, mypy and empty bodies, deprecating endpoints, endpoint names, and requests without an endpoint.
- [Building requests](requests.md): how parameters become the path, query string, headers and body, the helpers, and spreading a model into a part.
- [Responses](responses.md): how the return annotation decides what an endpoint returns, streaming, the open response, your own decoder, and errors for 4xx and 5xx responses.
- [Resources](resources.md): grouping endpoints under a path prefix, nesting them, and plain methods for logic such as pagination.
- [Client configuration](configuration.md): creating and closing a client, the base URL and `User-Agent` class defaults, authentication, logging and event hooks.
- [Async clients](async.md): `AsyncClientX` and `AsyncResource` for `async def` endpoints, concurrent requests, async streaming, and testing.
- [Testing](testing.md): testing a client without the network.
- [Errors](errors.md): the errors ClientX raises, and when.
- [API reference](reference.md): every public name, with its signature and arguments.
