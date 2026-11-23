from clientx import ClientX, method
from clientx.tools import list_tools, tool
from pydantic import BaseModel


class Product(BaseModel):
    id: int
    name: str


class Order(BaseModel):
    id: int
    status: str
    product_ids: list[int]


class ShopAPI(ClientX, base_url="https://api.shop.example.com"):
    @method.get("/orders/{order_id}")
    def order(self, order_id: int) -> Order:
        """Fetch an order, with the IDs of its products."""
        ...

    @method.get("/products/{product_id}")
    def product(self, product_id: int) -> Product:
        """Fetch a product."""
        ...

    @tool(read_only=True, idempotent=True)
    def order_products(self, order_id: int) -> list[Product]:
        """List the products in an order, in full.

        Args:
            order_id: The order's ID, as on its confirmation.
        """
        order = self.order(order_id)
        return [self.product(product_id) for product_id in order.product_ids]


api = ShopAPI()
print([each.name for each in list_tools(api)])  # ['order', 'product', 'order_products']
