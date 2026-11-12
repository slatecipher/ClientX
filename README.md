<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/slatecipher/ClientX/mainline/docs/assets/logo-dark.svg">
    <img alt="ClientX" src="https://raw.githubusercontent.com/slatecipher/ClientX/mainline/docs/assets/logo-light.svg" width="320">
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

The result is less scaffolding code and more focus on outcomes: authors spend less time on plumbing, and consumers spend less time guessing how to call your API correctly.

## Why ClientX

ClientX is inspired by FastAPI, which reads type hints to define server endpoints. ClientX applies the same idea to the client side:

- **The method signature is the contract.** Path placeholders, query parameters, headers, and bodies come from the method's parameters and annotations, so there's no request-building code to keep in sync.
- **Type checkers see real types.** Decorated methods keep their signatures, so editors and type checkers see the actual parameters and return types.
- **Mistakes surface early.** A missing return annotation or decoder raises an error when the class is defined, not on the first request.
- **Pydantic v2 throughout.** Send models as request bodies, query parameters, or headers, and decode responses into models.
- **Ready for AI agents.** `clientx.tools` turns a client's endpoints into tool definitions for AI models, built from the same signatures, docstrings, and types, and `clientx[mcp]` serves them as an MCP server in one call.
- **Built on httpx2.** Every `httpx2.Client` option is available, including auth, timeouts, proxies, and custom transports, and responses can be streamed.

ClientX is an independent project. It isn't affiliated with or endorsed by the FastAPI, Pydantic, or httpx2 projects.

## Features

- Declarative endpoint definitions with HTTP verb decorators.
- Typed response handling with pluggable decoders.
- Path parameter rendering from method arguments (e.g. `"/users/{user_id}"`).
- Request payload mapping from parameter names, `Annotated` metadata, or Pydantic models.
- Built-in deprecation warnings per endpoint.
- Endpoint tags, for grouping endpoints and filtering the AI tools built from them.
- Full access to `httpx2.Client` configuration through `ClientX(...)` kwargs.
- Endpoints described as AI tools, with JSON Schemas and safety hints (`clientx.tools`).
- A client served as an MCP server in one call (`clientx[mcp]`).

## Project status

ClientX is a personal project that I maintain in my spare time. Issues and pull requests are welcome, but replies may take a while, and there is no guaranteed response time.

ClientX is pre-1.0, so the API may change between minor versions. Changes are listed in the [changelog](https://github.com/slatecipher/ClientX/blob/mainline/CHANGELOG.md).

## Install

```bash
pip install clientx
```

To serve a client as an MCP server, install the `mcp` extra: `pip install "clientx[mcp]"`.

Using an AI coding assistant? Point it at [llms.txt](https://github.com/slatecipher/ClientX/blob/mainline/llms.txt), a compact guide to ClientX's patterns and pitfalls.

## Quickstart

```python
from typing import Annotated

from clientx import ClientX, Query, Resource
from clientx.decoders import ModelDecoder, TypeAdapterDecoder
from clientx.methods import get
from pydantic import BaseModel, TypeAdapter


class User(BaseModel):
    id: int
    name: str


class Users(Resource, prefix="/users"):
    @get("/{user_id}", decoder=ModelDecoder(User))
    def retrieve(self, user_id: int) -> User:
        """Fetch one user by ID."""
        ...

    @get(decoder=TypeAdapterDecoder(TypeAdapter(list[User])))
    def search(self, name: Annotated[str | None, Query()] = None) -> list[User]:
        """List users, or only those with this name."""
        ...


class ExampleAPI(ClientX, base_url="https://api.example.com", user_agent="example-app/1.0"):
    users = Users()


with ExampleAPI() as api:
    user = api.users.retrieve(42)  # GET /users/42 -> User
    matches = api.users.search(name="Ada")  # GET /users?name=Ada -> list[User]
```

- Endpoint bodies never run. ClientX builds each request from the method's signature, sends it, and returns the decoder's result.
- Type checkers see the real signatures: `api.users.retrieve(user_id: int) -> User`.
- A 4xx or 5xx response raises `httpx2.HTTPStatusError`.
- The `with` block closes the client's connections when it ends. It's optional: a long-lived client is created once and closed with `close()` at shutdown, as [Closing a client](https://github.com/slatecipher/ClientX/blob/mainline/docs/configuration.md#closing-a-client) explains.
- Using mypy? Turn off its `empty-body` check for your client modules, as [Defining endpoints](https://github.com/slatecipher/ClientX/blob/mainline/docs/endpoints.md#empty-method-bodies-and-mypy) explains.

## Guide

- [Defining endpoints](https://github.com/slatecipher/ClientX/blob/mainline/docs/endpoints.md): the verb decorators and their options, empty method bodies and mypy, and deprecating endpoints.
- [Resources](https://github.com/slatecipher/ClientX/blob/mainline/docs/resources.md): grouping endpoints under a path prefix, nesting them, and plain methods for logic such as pagination.
- [Return types and decoders](https://github.com/slatecipher/ClientX/blob/mainline/docs/decoders.md): `ModelDecoder`, `TypeAdapterDecoder`, `FromResponseDecoder`, the simple decoders, your own, and streaming.
- [Building requests](https://github.com/slatecipher/ClientX/blob/mainline/docs/requests.md): how parameters become the path, query string, headers, form fields, JSON body, and files.
- [Client configuration](https://github.com/slatecipher/ClientX/blob/mainline/docs/configuration.md): creating and closing a client, class defaults for the base URL and `User-Agent`, errors for 4xx and 5xx responses, and argument validation.
- [Logging](https://github.com/slatecipher/ClientX/blob/mainline/docs/logging.md): ClientX's debug records, and your own request logging.
- [AI tools and MCP](https://github.com/slatecipher/ClientX/blob/mainline/docs/ai-tools.md): endpoints as AI tools, serving a client over MCP, and listing a client's endpoints.
- [Testing](https://github.com/slatecipher/ClientX/blob/mainline/docs/testing.md): testing a client, its tools, and an MCP server without the network.
- [Errors](https://github.com/slatecipher/ClientX/blob/mainline/docs/errors.md): the errors ClientX raises, and when.

## Development

See [CONTRIBUTING.md](https://github.com/slatecipher/ClientX/blob/mainline/CONTRIBUTING.md) for setup, checks, and conventions.
