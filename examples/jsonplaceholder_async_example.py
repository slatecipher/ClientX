"""Fetch JSONPlaceholder data concurrently with an async client.

Run with `uv run python examples/jsonplaceholder_async_example.py`. It needs network access.
"""

import asyncio
import time

from jsonplaceholder import AsyncJSONPlaceholder


async def main() -> None:
    async with AsyncJSONPlaceholder(timeout=10.0) as api:
        posts = await api.posts.list(user_id=1)  # GET /posts?userId=1
        print(f"User 1 wrote {len(posts)} posts.")

        # One post's comments at a time: each request waits for the one before it.
        started = time.perf_counter()
        for post in posts:
            await api.comments.list(post.id)
        one_at_a_time = time.perf_counter() - started

        # All at once: the requests overlap, sharing the client's connections.
        started = time.perf_counter()
        comments = await asyncio.gather(*(api.comments.list(post.id) for post in posts))
        all_at_once = time.perf_counter() - started

        print(f"Fetched the comments on {len(posts)} posts, {sum(map(len, comments))} in all:")
        print(f"  one at a time: {one_at_a_time:.2f} s")
        print(f"  all at once:   {all_at_once:.2f} s")

        # Different endpoints at once, each with its own type: a Post and a User.
        post, author = await asyncio.gather(api.posts.get(1), api.users.get(1))
        print(f"Post 1, {post.title!r}, is by {author.name}.")


if __name__ == "__main__":
    asyncio.run(main())
