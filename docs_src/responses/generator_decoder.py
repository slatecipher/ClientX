from collections.abc import Iterator

from clientx import ClientX, Response, method
from pydantic import BaseModel


class Event(BaseModel):
    id: int
    kind: str


def parse_events(response: Response) -> Iterator[Event]:
    """Yield an event for each line of JSON."""
    for line in response.iter_lines():
        if line:
            yield Event.model_validate_json(line)


class EventsAPI(ClientX):
    @method.get("/events", decoder=parse_events)
    def watch(self) -> Iterator[Event]: ...
