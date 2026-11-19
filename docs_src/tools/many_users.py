import contextvars
from collections.abc import Generator
from typing import Any

import httpx2
from clientx import AsyncClientX, method
from clientx.tools import list_tools
from pydantic import BaseModel


class Order(BaseModel):
    id: int
    status: str


class ShopAPI(AsyncClientX, base_url="https://api.shop.example.com"):
    @method.get("/orders/{order_id}")
    async def retrieve_order(self, order_id: int) -> Order:
        """Fetch one of the user's orders, with its status."""
        ...


# The upstream token of the user whose tool call is running.
upstream_token: contextvars.ContextVar[str] = contextvars.ContextVar("upstream_token")


class CurrentUserAuth(httpx2.Auth):
    """Send the upstream token of the user whose tool call is running."""

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {upstream_token.get()}"
        yield request


# Each user's upstream token, stored when they connected: use a real store.
upstream_tokens: dict[str, str] = {}

api = ShopAPI(auth=CurrentUserAuth())  # one client and one connection pool, for every user
tools = {tool.name: tool for tool in list_tools(api)}  # described once, at startup


async def handle_tool_call(user_id: str, name: str, arguments: dict[str, Any]) -> Any:
    """Run a tool for a user your server has already authenticated."""
    upstream_token.set(upstream_tokens[user_id])
    return await tools[name].acall(arguments)
