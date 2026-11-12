"""Call a few JSONPlaceholder endpoints, then list the client's endpoints as AI tools.

Run with `uv run python examples/jsonplaceholder_example.py`. It needs network access.
"""

import httpx2
from jsonplaceholder import JSONPlaceholder, NewPost, PostChanges

from clientx.exceptions import ArgumentValidationError
from clientx.tools import list_tools


def main() -> None:
    # The class ships its base URL and User-Agent, so only the timeout is set here.
    with JSONPlaceholder(timeout=10.0) as api:
        posts = api.posts.list(user_id=1)  # GET /posts?userId=1
        print(f"User 1 wrote {len(posts)} posts. The first: {posts[0].title!r}")

        post = api.posts.get(1)  # GET /posts/1
        author = api.users.get(post.user_id)  # GET /users/1
        comments = api.comments.list(post.id)  # GET /posts/1/comments
        print(f"Post 1 is by {author.name} of {author.company.name} and has {len(comments)} comments.")
        print(f"The first comment is from {comments[0].email}: {comments[0].name!r}")

        # JSONPlaceholder answers writes realistically but doesn't save them.
        created = api.posts.create(NewPost(user_id=1, title="Hello from ClientX", body="Typed and declarative."))
        print(f"Created post {created.id}: {created.title!r}")
        updated = api.posts.update(1, PostChanges(title="A better title"))  # PATCH sends only the title
        print(f"Updated post 1: {updated.title!r}, body unchanged: {updated.body[:30]!r}...")
        api.posts.delete(1)
        print("Deleted post 1.")

        try:
            api.posts.get(1000)  # A 404 raises httpx2.HTTPStatusError before the decoder runs.
        except httpx2.HTTPStatusError as exc:
            print(f"Post 1000 doesn't exist: HTTP {exc.response.status_code}")

        # Argument validation is off by default, so post 1000 was sent above. A second client for the same
        # API, with it on, checks the bounds in the endpoint's annotations (post IDs are 1 to 100) first.
        with JSONPlaceholder(validate_arguments=True) as checked:
            try:
                checked.posts.get(1000)
            except ArgumentValidationError as exc:
                print(f"With validate_arguments=True, post 1000 isn't sent: {exc.parameter} must be 1 to 100")

        print("\nAI tools:")
        for tool in list_tools(api):
            hints = [
                hint
                for hint, applies in (
                    ("read-only", tool.read_only),
                    ("destructive", tool.destructive),
                    ("idempotent", tool.idempotent),
                )
                if applies
            ]
            route = f"{tool.method} {tool.path}"
            print(f"  {tool.name:<15} {route:<32} {', '.join(hints) or '-'}")


if __name__ == "__main__":
    main()
