from collections.abc import Generator

import httpx2
from clientx import AsyncClientX, method
from clientx.fastmcp import fastmcp_tool
from clientx.tools import list_tools
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel


class Order(BaseModel):
    id: int
    status: str


class ShopAPI(AsyncClientX, base_url="https://api.shop.example.com"):
    @method.get("/orders/{order_id}")
    async def retrieve_order(self, order_id: int) -> Order:
        """Fetch one of the user's orders, with its status."""
        ...


# Each user's upstream token, stored when they authorized your server with the
# shop's API: use a real store.
upstream_tokens: dict[str, str] = {}


class CurrentUserAuth(httpx2.Auth):
    """Send the upstream token of the user whose tool call is running."""

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        # The token the user's app sent your server, which its auth validated.
        caller = get_access_token()
        if caller is None or caller.subject is None:
            raise RuntimeError("No signed-in user: give the server auth=.")
        request.headers["Authorization"] = f"Bearer {upstream_tokens[caller.subject]}"
        yield request


api = ShopAPI(auth=CurrentUserAuth())  # one client and one connection pool, for every user
server = FastMCP(
    "shop",
    auth=JWTVerifier(
        jwks_uri="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="https://mcp.shop.example.com",
    ),
)
for tool in list_tools(api):
    server.add_tool(fastmcp_tool(tool))

if __name__ == "__main__":
    server.run(transport="http")
