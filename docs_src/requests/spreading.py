from typing import Annotated

from clientx import ClientX, Query, Response, method
from pydantic import BaseModel


class Filters(BaseModel):
    state: str = "open"
    assignee: str | None = None
    labels: list[str] = []


class IssuesAPI(ClientX):
    @method.get("/issues")
    def search(self, filters: Annotated[Filters, Query()]) -> Response: ...
