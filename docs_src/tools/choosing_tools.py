from typing import Annotated, Any

from clientx import ClientX, Json, Resource, method
from clientx.tools import list_tools


class Products(Resource, prefix="/products", tags=["ai"]):
    @method.post("/search")
    def search(self, query: Annotated[str, Json()]) -> list[dict[str, Any]]:
        """Search the catalog by name or description."""
        ...


class Orders(Resource, prefix="/orders"):
    @method.get("/{order_id}", tags=["ai"])
    def retrieve(self, order_id: int) -> dict[str, Any]:
        """Fetch an order, with its status."""
        ...

    @method.delete("/{order_id}")
    def cancel(self, order_id: int) -> None:
        """Cancel an order."""
        ...


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    products = Products()
    orders = Orders()


api = ShopAPI()
tools = [tool for tool in list_tools(api) if "ai" in tool.tags]  # products_search, orders_retrieve
