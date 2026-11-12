# Logging

ClientX logs one record per endpoint call on the `clientx` logger, at `DEBUG` level, after the response arrives or the request fails:

```
DEBUG:clientx:ClientX request: POST /users/42 -> 201 in 12.3 ms (UsersClient.update_user)
```

To see these records:

```python
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("clientx").setLevel(logging.DEBUG)
```

Each record also has these attributes, for structured log handlers such as JSON formatters:

| Attribute | Example | Meaning |
|---|---|---|
| `clientx_endpoint` | `"UsersClient.update_user"` | The endpoint method. |
| `clientx_method` | `"POST"` | The HTTP method. |
| `clientx_path` | `"/users/42"` | The endpoint's rendered path, relative to the base URL, without the query string. With a base URL of `https://api.example.com/v1`, it's `/users/42`, not `/v1/users/42`. |
| `clientx_parts` | `["headers", "json"]` | The names of the request parts sent. |
| `clientx_stream` | `False` | Whether the response is streamed. For a stream, the elapsed time covers the response headers only. |
| `clientx_status` | `201` | The status code, or `None` if no response arrived. |
| `clientx_elapsed_ms` | `12.3` | Time to send the request and receive the response, in milliseconds. |
| `clientx_error` | `None` | The exception's class name if the call failed, such as `"ConnectTimeout"`, or `"HTTPStatusError"` with the status for a 4xx or 5xx response. ClientX re-raises the exception. The record is written when the response arrives, before any decoder runs, so a decoder's exception isn't recorded. |

ClientX never logs header values, request bodies, or query strings. The path is logged with its placeholders filled in (`/users/42`), so keep secrets out of path parameters.

httpx2 also logs every request, at `INFO` level on the `httpx2` logger, and its message includes the full URL with the query string. To hide those records, use `logging.getLogger("httpx2").setLevel(logging.WARNING)`.

## Your own request logging

To log requests in your own format or with your own logger, use httpx2's event hooks. ClientX passes `event_hooks` through to `httpx2.Client`:

```python
import logging

import httpx2
from clientx import ClientX

log = logging.getLogger("myapp.http")


def log_request(request: httpx2.Request) -> None:
    log.info("-> %s %s", request.method, request.url.path)


def log_response(response: httpx2.Response) -> None:
    log.info("<- %s %s %s", response.request.method, response.request.url.path, response.status_code)


client = ClientX(
    "https://api.example.com",
    event_hooks={"request": [log_request], "response": [log_response]},
)
```

- Request hooks receive the `httpx2.Request` just before it's sent. Response hooks receive the `httpx2.Response` once its headers arrive, before the body is read.
- Hooks run for every request, including streamed ones. Don't read the body in a response hook: for a streamed endpoint, that would load the whole stream.
- Hooks see everything, including header values and query strings, so redact anything sensitive yourself.
- Hooks don't know which endpoint was called. ClientX's own records do (`clientx_endpoint`), so you can use both.

Deprecated endpoints emit a `DeprecationWarning` through Python's `warnings` module, not a log record. Python hides `DeprecationWarning` by default unless it's triggered by code in `__main__` or under a test runner such as pytest. To send warnings to your logs, call `logging.captureWarnings(True)`; they then appear on the `py.warnings` logger.
