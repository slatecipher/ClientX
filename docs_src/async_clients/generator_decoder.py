from collections.abc import AsyncIterator

from clientx import AsyncClientX, Response, method
from pydantic import BaseModel


class Event(BaseModel):
    id: int
    kind: str


async def parse_events(response: Response) -> AsyncIterator[Event]:
    """Yield an event for each line of JSON."""
    async for line in response.aiter_lines():
        if line:
            yield Event.model_validate_json(line)


class EventsAPI(AsyncClientX):
    @method.get("/events", decoder=parse_events)
    async def watch(self) -> AsyncIterator[Event]: ...
