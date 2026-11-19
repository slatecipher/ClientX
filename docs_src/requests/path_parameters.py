from clientx import ClientX, Response, method


class ReposAPI(ClientX):
    @method.get("/repos/{owner}/{repo}/contents/{file_path:path}")
    def get_file(self, owner: str, repo: str, file_path: str) -> Response: ...
