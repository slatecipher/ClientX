"""Call a few JSONPlaceholder endpoints, then list the client's endpoints as AI tools.

Run with `uv run python examples/jsonplaceholder_example.py`. It needs network access.
"""

import httpx2
from jsonplaceholder import JSONPLACEHOLDER_URL, JSONPlaceholder, NewPost, PostChanges, raise_for_status

from clientx.tools import list_tools


def main() -> None:
    # ClientX doesn't check status codes: the hook raises httpx2.HTTPStatusError for 4xx and 5xx responses.
    with JSONPlaceholder(JSONPLACEHOLDER_URL, timeout=10.0, event_hooks={"response": [raise_for_status]}) as api:
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
            api.posts.get(1000)  # 404: raised by the hook, not decoded into a Post
        except httpx2.HTTPStatusError as exc:
            print(f"Post 1000 doesn't exist: HTTP {exc.response.status_code}")

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
