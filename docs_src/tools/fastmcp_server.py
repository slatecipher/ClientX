from typing import Any

from clientx import AsyncClientX, method
from clientx.fastmcp import fastmcp_tool
from clientx.tools import list_tools
from fastmcp import FastMCP


class ShopAPI(AsyncClientX, base_url="https://api.shop.example.com"):
    @method.get("/products/{product_id}")
    async def product(self, product_id: int) -> dict[str, Any]:
        """Fetch a product, with its price and stock."""
        ...

    @method.delete("/orders/{order_id}")
    async def cancel_order(self, order_id: int) -> None:
        """Cancel an order."""
        ...


api = ShopAPI()
# The read-only tools: product, but not cancel_order.
server = FastMCP("shop", tools=[fastmcp_tool(tool) for tool in list_tools(api) if tool.read_only])


@server.tool
def shipping_days(country: str) -> int:
    """Return how many days shipping to a country takes."""
    return 2 if country == "US" else 7


if __name__ == "__main__":
    server.run()  # Over stdio, by default.
