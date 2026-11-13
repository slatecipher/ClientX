import math
import time
from base64 import b64encode
from collections.abc import Generator
from urllib.parse import quote_plus

from clientx import Auth, Request, Response


class ClientCredentials(Auth):
    """OAuth 2 client credentials: get a bearer token with a client ID and secret, and send it with every request.

    The token is reused until it expires. If the API rejects it sooner with a 401, the request is retried once
    with a new token. Pass an instance as a client's `auth=`.

    Because the flow reads the token response, `requires_response_body` makes httpx2 read every response in full,
    so a streaming endpoint on a client using this class still works but isn't streamed.
    """

    requires_response_body = True  # The flow reads the token response's JSON.

    def __init__(self, token_url: str, client_id: str, client_secret: str, scope: str | None = None) -> None:
        self.token_url = token_url
        self.scope = scope
        # RFC 6749, section 2.3.1: form-encode the ID and secret, then send them with HTTP Basic authentication.
        credentials = f"{quote_plus(client_id)}:{quote_plus(client_secret)}"
        self.client_authorization = f"Basic {b64encode(credentials.encode()).decode()}"
        self.access_token = ""
        self.expires_at = 0.0

    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        if time.monotonic() >= self.expires_at:
            yield from self.fetch_token()
        request.headers["Authorization"] = f"Bearer {self.access_token}"
        response = yield request
        if response.status_code == 401:
            yield from self.fetch_token()
            request.headers["Authorization"] = f"Bearer {self.access_token}"
            yield request

    def fetch_token(self) -> Generator[Request, Response, None]:
        data = {"grant_type": "client_credentials"}
        if self.scope:
            data["scope"] = self.scope
        headers = {"Authorization": self.client_authorization}
        response = yield Request("POST", self.token_url, data=data, headers=headers)
        response.raise_for_status()
        token = response.json()
        self.access_token = token["access_token"]
        # Renew 30 seconds early, so the token can't expire on its way. Without expires_in (it's optional),
        # keep the token until the API rejects it.
        lifetime = token.get("expires_in")
        self.expires_at = math.inf if lifetime is None else time.monotonic() + lifetime - 30
