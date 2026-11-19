from enum import Enum
from typing import Annotated

from clientx import ClientX, Header, Query, Response, method


class Sort(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class ItemsAPI(ClientX):
    @method.get("/items")
    def list_items(
        self,
        item_type: Annotated[str, Query(alias="type")],
        sort: Annotated[Sort, Query()] = Sort.NEWEST,
        tags: Annotated[list[str] | None, Query()] = None,
        request_id: Annotated[str | None, Header()] = None,
    ) -> Response: ...
