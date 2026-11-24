from clientx import ArgumentError, ClientX, Resource, method
from clientx.tools import list_tools, tool
from pydantic import BaseModel


class Group(BaseModel):
    id: int
    name: str
    is_default: bool


class Groups(Resource, prefix="/groups"):
    @method.get("/{name}")
    def retrieve(self, name: str) -> Group:
        """Fetch a group, and whether it's the default group."""
        ...

    @method.delete("/{name}")
    def _delete(self, name: str) -> None: ...

    @tool(destructive=True, idempotent=True)
    def delete(self, name: str) -> None:
        """Delete a group, which removes its members from it.

        The default group can't be deleted.
        """
        # The API would delete the default group too, and every user would
        # lose theirs.
        if self.retrieve(name).is_default:
            raise ArgumentError(f"Refused to delete {name!r}: it's the default group.", parameter="name")
        self._delete(name)


class TeamAPI(ClientX, base_url="https://api.team.example.com"):
    groups = Groups()


api = TeamAPI()
print([each.name for each in list_tools(api)])  # ['groups_retrieve', 'groups_delete']
