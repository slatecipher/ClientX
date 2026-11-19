"""The docs' samples run, and each page shows them as they are.

Each sample is a module in docs_src/, so ``make lint`` and ``make typecheck``
check it like any other code, in pyright's strict mode. GitHub and PyPI can't
include a file, so a page shows a copy of each of its samples, which ``make
docs`` (scripts/sync_docs.py) keeps up to date. A block that's deliberately
incomplete is fenced as ```python no-check: GitHub still highlights it as
Python, since it reads only the first word.

Each sample also runs on its own, up to the first request it sends, which
raises instead of reaching the network. That catches what only running finds,
such as the ``DefinitionError`` for a parameter without a helper.

The ``Send`` table in docs/requests.md lists the helpers each option works
with, and must match what the code allows.
"""

import contextlib
import re
import runpy
from dataclasses import fields
from pathlib import Path
from typing import Any, NoReturn

import httpx2
import pytest

from clientx import Send
from clientx._planner import _SPECS  # pyright: ignore[reportPrivateUsage]

ROOT = Path(__file__).parent.parent
SAMPLES = sorted((ROOT / "docs_src").rglob("*.py"))
SYNC: dict[str, Any] = runpy.run_path(str(ROOT / "scripts" / "sync_docs.py"))


def test_each_page_shows_its_samples_as_they_are() -> None:
    stale = [page.name for page in SYNC["PAGES"] if SYNC["synced"](page) != page.read_text()]
    assert stale == [], f"Run `make docs` to copy the samples in docs_src/ into {', '.join(stale)}."


def test_each_python_block_shows_a_sample_and_each_sample_is_shown() -> None:
    unshown: list[str] = []
    for page in SYNC["PAGES"]:
        lines = page.read_text().splitlines()
        unshown += [
            f"{page.name}:{number}"
            for number, line in enumerate(lines, start=1)
            if line == "```python" and (number == 1 or not SYNC["MARKER"].fullmatch(lines[number - 2]))
        ]
    assert unshown == [], "Move each block's code into docs_src/ and name the file in a comment before the block."
    assert SYNC["shown_samples"]() == set(SAMPLES)


class RequestSentError(Exception):
    """Stop a sample at the first request it sends."""


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda path: str(path.relative_to(ROOT / "docs_src")))
def test_the_sample_runs(sample: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stop(*_: object) -> NoReturn:
        raise RequestSentError

    async def astop(*_: object) -> NoReturn:
        raise RequestSentError

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", stop)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", astop)
    with contextlib.suppress(RequestSentError):
        runpy.run_path(str(sample), run_name="docs_sample")


def test_the_send_table_lists_the_helpers_each_option_works_with() -> None:
    # Each spec's send_options decide where an option works; the table must say
    # the same, for every Send option.
    page = (ROOT / "docs/requests.md").read_text()
    table = page[page.index("| Option | Works with | Effect |") :].split("\n\n", 1)[0]
    documented: dict[str, set[str]] = {}
    for row in table.splitlines()[2:]:
        option, works_with = row.split("|")[1:3]
        documented[option.strip().strip("`").split("=")[0]] = set(re.findall(r"`(\w+\(\))`", works_with))
    allowed = {
        option.name: {spec.helper for spec in _SPECS.values() if option.name in spec.send_options}
        for option in fields(Send)
    }
    assert documented == allowed
