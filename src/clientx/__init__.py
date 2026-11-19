"""A typed, declarative HTTP API client framework for Python."""

from httpx2 import Auth, Request, Response, Timeout

from clientx import method
from clientx._client import AsyncClientX, AsyncResource, ClientX, Resource
from clientx._version import __version__
from clientx.arguments import Body, File, Form, Header, Json, Query, Send, Url
from clientx.exceptions import ArgumentError, ClientXError, DefinitionError

__all__ = [
    # clientx._version
    "__version__",
    # httpx2
    "Auth",
    "Request",
    "Response",
    "Timeout",
    # clientx._client
    "AsyncClientX",
    "AsyncResource",
    "ClientX",
    "Resource",
    # clientx.arguments
    "Body",
    "File",
    "Form",
    "Header",
    "Json",
    "Query",
    "Send",
    "Url",
    # clientx.exceptions
    "ArgumentError",
    "ClientXError",
    "DefinitionError",
    # submodules
    "method",
]
