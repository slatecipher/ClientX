from typing import Annotated

import httpx2
from clientx import ClientX, Query, Resource, method
from pydantic import BaseModel


class NamedLink(BaseModel):
    name: str
    url: str


class Page(BaseModel):
    count: int
    next: str | None
    results: list[NamedLink]


class Pokemon(BaseModel):
    id: int
    name: str


class PokemonResource(Resource, prefix="/pokemon"):
    @method.get()
    def page(self, limit: Annotated[int, Query()] = 20, offset: Annotated[int, Query()] = 0) -> Page:
        """List Pokémon, one page at a time."""
        ...

    @method.get("/{name}")
    def retrieve(self, name: str) -> Pokemon:
        """Fetch one Pokémon by its lowercase name."""
        ...

    def next_page(self, page: Page) -> Page | None:
        """Fetch the page after `page`, or return None after the last one."""
        if page.next is None:
            return None
        params = httpx2.URL(page.next).params
        return self.page(limit=int(params["limit"]), offset=int(params["offset"]))

    def find(self, name: str) -> Pokemon:
        """Fetch a Pokémon by name, whatever its case or surrounding spaces."""
        return self.retrieve(name.strip().lower())


class PokeAPI(ClientX):
    pokemon = PokemonResource()


with PokeAPI("https://pokeapi.co/api/v2") as api:
    first = api.pokemon.page()
    second = api.pokemon.next_page(first)
