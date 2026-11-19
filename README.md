<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-light.svg">
    <img alt="ClientX" src="https://raw.githubusercontent.com/slatecipher/ClientX/mainline/docs/assets/logo-light.svg" width="400">
  </picture>
</h1>

<p align="center">
  <em>Typed, declarative HTTP API clients for Python 3.12+.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/clientx/"><img src="https://img.shields.io/pypi/v/clientx" alt="PyPI"></a>
  <a href="https://pypi.org/project/clientx/"><img src="https://img.shields.io/pypi/pyversions/clientx" alt="Python versions"></a>
  <a href="https://github.com/slatecipher/ClientX/actions/workflows/ci.yml"><img src="https://github.com/slatecipher/ClientX/actions/workflows/ci.yml/badge.svg?branch=mainline" alt="CI"></a>
  <a href="https://github.com/slatecipher/ClientX/blob/mainline/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
</p>

## Overview

ClientX is a declarative API client framework designed to make writing and maintaining API clients easier while keeping the client contract explicit and well documented.

For client authors, ClientX reduces boilerplate by turning typed endpoint definitions into concrete `httpx2` requests and centralizing request/response behavior. For client consumers, it pushes API contracts and guard rails into the client itself, helping prevent avoidable runtime mistakes and making integrations more predictable.

The result is less scaffolding and more focus on outcomes: authors, human or AI, spend less time on plumbing, and the developers and AI agents calling your API spend less time guessing how to use it correctly.

## Why ClientX

ClientX is inspired by FastAPI, which reads type hints to define server endpoints. ClientX applies the same idea to the client side:

- **The method signature is the contract.** Path placeholders, query parameters, headers and bodies come from the method's parameters and annotations, so there's no request-building code to keep in sync.
- **The return annotation decodes the response.** `-> User` returns the JSON body validated as a `User`, `-> Iterator[str]` streams it line by line, and `-> Response` returns the response itself.
- **Type checkers see real types.** Decorated methods keep their signatures, so editors and type checkers see the actual parameters and return types.
- **Sync or async.** Write endpoints as `def` methods on a `ClientX`, or as `async def` methods on an `AsyncClientX`, with the same decorators.
- **Mistakes surface early.** A missing return annotation, a parameter that doesn't say where it goes, a placeholder that names no parameter, or a type ClientX can't decode raises an error when the class is defined, not on the first request.
- **Pydantic v2 throughout.** Send models as JSON bodies, or spread them into query parameters, headers or form fields, and decode responses into models.
- **Built on httpx2.** A client is an `httpx2.Client`, or an `httpx2.AsyncClient`, so every option is available, including auth, timeouts, proxies and custom transports.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Responses decoded from the return annotation, with streaming, and your own decoder when you need one.
- Path parameters filled from method arguments and percent-encoded (e.g. `"/users/{user_id}"`).
- Request parts declared with helpers named like FastAPI's (`Query`, `Header`, `Json`, `Body`, `Form`, `File`): every parameter but a path placeholder's says where it goes.
- Resources that group endpoints under a path prefix.
- Built-in deprecation warnings per endpoint.
- Full access to `httpx2.Client` configuration through `ClientX(...)` arguments.
- Async clients (`AsyncClientX`, `AsyncResource`) with the same decorators, for `async def` endpoints.

## Project status

ClientX is a personal project that I maintain in my spare time. Issues and pull requests are welcome, but replies may take a while, and there is no guaranteed response time.

ClientX is pre-1.0, so the API may change between minor versions. Changes are listed in the [changelog](https://github.com/slatecipher/ClientX/blob/mainline/CHANGELOG.md).

## Install

```bash
pip install clientx
```

Using an AI coding assistant? Point it at [llms.txt](https://github.com/slatecipher/ClientX/blob/mainline/llms.txt), a compact guide to ClientX's patterns and pitfalls.

## Quickstart

```python
from typing import Annotated

from clientx import ClientX, Query, Resource, method
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @method.get("/{user_id}")
    def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @method.get()
    def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(ClientX, user_agent="example-app/1.0"):
    users = Users()


with ExampleAPI("https://api.example.com") as api:
    user = api.users.retrieve(42)  # GET /users/42 -> User
    matches = api.users.search(name="Ada")  # GET /users?name=Ada -> list[User]
```

- Endpoint bodies never run. ClientX builds each request from the method's signature, sends it, and decodes the response into the return annotation.
- Type checkers see the real signatures: `api.users.retrieve(user_id: int) -> User`.
- A 4xx or 5xx response raises `httpx2.HTTPStatusError`.
- The `with` block closes the client's connections when it ends. It's optional: a long-lived client is created once and closed with `close()` at shutdown, as [Closing a client](https://github.com/slatecipher/ClientX/blob/mainline/docs/configuration.md#closing-a-client) explains.
- For async code, subclass `AsyncClientX` and `AsyncResource`, write the endpoints as `async def` methods, and `await` them, as [Async clients](https://github.com/slatecipher/ClientX/blob/mainline/docs/async.md) explains.
- Using mypy? Turn off its `empty-body` check for your client modules, as [Defining endpoints](https://github.com/slatecipher/ClientX/blob/mainline/docs/endpoints.md#empty-method-bodies-and-mypy) explains.

## Guide

- [Defining endpoints](https://github.com/slatecipher/ClientX/blob/mainline/docs/endpoints.md): the verb decorators and their options, the rules for an endpoint method, deprecating endpoints, and endpoint names.
- [Building requests](https://github.com/slatecipher/ClientX/blob/mainline/docs/requests.md): how parameters become the path, query string, headers and body.
- [Responses](https://github.com/slatecipher/ClientX/blob/mainline/docs/responses.md): how the return annotation decides what an endpoint returns, streaming, your own decoder, and errors for 4xx and 5xx responses.
- [Resources](https://github.com/slatecipher/ClientX/blob/mainline/docs/resources.md): grouping endpoints under a path prefix, nesting them, and plain methods for logic such as pagination.
- [Client configuration](https://github.com/slatecipher/ClientX/blob/mainline/docs/configuration.md): creating and closing a client, the `User-Agent` class default, authentication, logging and event hooks.
- [Async clients](https://github.com/slatecipher/ClientX/blob/mainline/docs/async.md): `AsyncClientX` and `AsyncResource` for `async def` endpoints, concurrent requests, and async streaming.
- [Testing](https://github.com/slatecipher/ClientX/blob/mainline/docs/testing.md): testing a client without the network.
- [Errors](https://github.com/slatecipher/ClientX/blob/mainline/docs/errors.md): the errors ClientX raises, and when.

## Development

See [CONTRIBUTING.md](https://github.com/slatecipher/ClientX/blob/mainline/CONTRIBUTING.md) for setup, checks, and conventions.

## License

ClientX is released under the [MIT License](https://github.com/slatecipher/ClientX/blob/mainline/LICENSE).

ClientX is an independent project. It isn't affiliated with or endorsed by the FastAPI, Pydantic, or httpx2 projects.
