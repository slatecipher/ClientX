from collections.abc import Iterator

from clientx import ClientX, method


class LogsAPI(ClientX):
    @method.get("/jobs/{job_id}/log")
    def follow_log(self, job_id: str) -> Iterator[str]: ...


with LogsAPI("https://api.example.com") as api:
    for line in api.follow_log("build-42"):
        print(line)
