"""Call an API that needs an OAuth 2 bearer token, which the client gets with a client ID and secret.

Run with `uv run python examples/oauth2_example.py`. It needs network access. It uses Duende's public demo server,
which publishes its demo client ID (`m2m`) and secret (`secret`). For your own API, read the ID and secret from
the environment or a secrets manager, never from the source code.
"""

import httpx2

from oauth2 import TOKEN_URL, ClientCredentials, DemoAPI


def log_request(request: httpx2.Request) -> None:
    """Print each request the client sends, the token requests included.

    A request hook is for logging like this (see docs/logging.md), not for adding credentials: those go in `auth=`.
    Never print header values here, since they include the token.
    """
    print(f"  -> {request.method} {request.url}")


def main() -> None:
    # The demo server's published client. Never put a real secret in source code.
    auth = ClientCredentials(TOKEN_URL, client_id="m2m", client_secret="secret", scope="api")  # noqa: S106
    with DemoAPI(auth=auth, event_hooks={"request": [log_request]}, timeout=10.0) as api:
        print("First call: the client gets a token, then sends the request with it.")
        claims = {claim.type: claim.value for claim in api.claims()}
        print(f"The API saw client {claims['client_id']!r} with scope {claims['scope']!r}.")

        print("Second call: the token is reused, so there's no token request.")
        api.claims()

    # A wrong secret fails at the token endpoint, and the API request is never sent.
    with DemoAPI(auth=ClientCredentials(TOKEN_URL, "m2m", "wrong", scope="api"), timeout=10.0) as api:
        try:
            api.claims()
        except httpx2.HTTPStatusError as exc:
            print(f"Wrong secret: the token endpoint answers HTTP {exc.response.status_code} {exc.response.json()}")

    # Without auth=, the API refuses the call.
    with DemoAPI(timeout=10.0) as api:
        try:
            api.claims()
        except httpx2.HTTPStatusError as exc:
            print(f"Without auth=, the API answers HTTP {exc.response.status_code}.")


if __name__ == "__main__":
    main()
