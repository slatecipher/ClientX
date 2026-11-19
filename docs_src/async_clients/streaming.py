from collections.abc import AsyncIterator

from clientx import AsyncClientX, method


class EventsAPI(AsyncClientX):
    @method.get("/events")
    async def events(self) -> AsyncIterator[str]: ...


async def print_events() -> None:
    async with EventsAPI("https://api.example.com") as api:
        async for line in await api.events():
            print(line)
