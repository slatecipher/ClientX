from typing import Annotated, Any

from clientx import ClientX, Json, Query, method
from clientx.tools import ToolOptions, list_tools


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    @method.post("/search", tool_options=ToolOptions(read_only=True, idempotent=True))
    def search(self, query: Annotated[str, Json()]) -> list[dict[str, Any]]:
        """Search the catalog by name or description."""
        ...

    @method.get("/cart/add", tool_options=ToolOptions(read_only=False, idempotent=False))
    def add_to_cart(self, product_id: Annotated[int, Query()]) -> dict[str, Any]:
        """Add one of a product to the cart."""
        ...


api = ShopAPI()
read_only = [tool for tool in list_tools(api) if tool.read_only]  # search
