from clientx import ClientX, Response, method
from pydantic import BaseModel, TypeAdapter


class Item(BaseModel):
    id: int
    name: str


ITEMS = TypeAdapter(list[Item])


def items_in_envelope(response: Response) -> list[Item]:
    """Read the items from a body such as {"data": {"items": [...]}}."""
    return ITEMS.validate_python(response.json()["data"]["items"])


class ItemsAPI(ClientX):
    @method.get("/items", decoder=items_in_envelope)
    def list_items(self) -> list[Item]: ...
