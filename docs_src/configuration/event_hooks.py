import logging

import httpx2
from clientx import ClientX

log = logging.getLogger("myapp.http")


def log_request(request: httpx2.Request) -> None:
    log.info("-> %s %s", request.method, request.url.path)


def log_response(response: httpx2.Response) -> None:
    log.info("<- %s %s %s", response.request.method, response.request.url.path, response.status_code)


class ExampleAPI(ClientX): ...


api = ExampleAPI(
    "https://api.example.com",
    event_hooks={"request": [log_request], "response": [log_response]},
)
