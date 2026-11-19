"""Code samples in the docs type-check under pyright's strict mode, and run.

Each ```python block in a checked file is type-checked on its own, so it must
carry its own imports, as a reader copying it would need. A block that's
deliberately incomplete is fenced as ```python no-check: GitHub still
highlights it as Python, since it reads only the first word.

Each block also runs on its own, up to the first request it sends, which raises
instead of reaching the network. That catches what only running finds, such as
the ``DefinitionError`` for a parameter without a helper.

The ``Send`` table in docs/requests.md lists the helpers each option works
with, and must match what the code allows.
"""

import json
import re
import subprocess  # noqa: S404 - runs pyright on the docs' own samples
import sys
import traceback
import types
from dataclasses import dataclass, fields
from pathlib import Path
from typing import NoReturn

import httpx2
import pytest

from clientx import Send
from clientx._planner import _SPECS  # pyright: ignore[reportPrivateUsage]

ROOT = Path(__file__).parent.parent

# Every page with code samples: the guide, the README and llms.txt.
CHECKED = [
    *(str(path.relative_to(ROOT)) for path in sorted(ROOT.glob("docs/*.md"))),
    "README.md",
    "llms.txt",
]

FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


@dataclass(frozen=True)
class Sample:
    file: str
    line: int  # The line of the sample's first line of code in its file.
    code: str


def samples_in(path: Path, name: str) -> list[Sample]:
    """Return the python blocks in a Markdown file, except no-check ones."""
    lines = path.read_text().splitlines()
    samples: list[Sample] = []
    index = 0
    while index < len(lines):
        opening = FENCE.match(lines[index])
        index += 1
        if opening is None:
            continue
        indent, fence = len(opening["indent"]), opening["fence"]
        start = index
        while index < len(lines) and lines[index].strip() != fence:
            index += 1
        # A block in a list item is indented like its fence: remove that much.
        code = "\n".join(line[indent:] for line in lines[start:index])
        index += 1
        words = opening["info"].split()
        if words[:1] == ["python"] and "no-check" not in words[1:]:
            samples.append(Sample(name, start + 1, code + "\n"))
    return samples


def type_errors(samples: list[Sample], directory: Path) -> list[str]:
    """Type-check each sample on its own, and return its errors.

    Each error is ``file:line: message``, with the line in the Markdown file.
    """
    for number, sample in enumerate(samples):
        (directory / f"sample_{number}.py").write_text(sample.code)
    config = {"typeCheckingMode": "strict", "pythonVersion": "3.12"}
    (directory / "pyrightconfig.json").write_text(json.dumps(config))
    # The arguments are fixed, and the files are the docs' own samples.
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pyright",
            "--outputjson",
            "--pythonpath",
            sys.executable,
            "--project",
            str(directory),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(result.stdout)
    errors: list[str] = []
    for diagnostic in report["generalDiagnostics"]:
        if diagnostic["severity"] not in {"error", "warning"}:
            continue
        sample = samples[int(Path(diagnostic["file"]).stem.removeprefix("sample_"))]
        line = sample.line + diagnostic["range"]["start"]["line"]
        errors.append(f"{sample.file}:{line}: {diagnostic['message']}")
    return errors


class RequestSentError(Exception):
    """Stop a sample at the first request it sends."""


def run_errors(samples: list[Sample], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run each sample in a module of its own, and return its errors.

    A sample stops at the first request it sends, which raises
    ``RequestSentError`` instead of reaching the network. Each error is
    ``file:line: type: message``, with the line in the Markdown file.
    """

    def stop(*_: object) -> NoReturn:
        raise RequestSentError

    async def astop(*_: object) -> NoReturn:
        raise RequestSentError

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", stop)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", astop)
    errors: list[str] = []
    for number, sample in enumerate(samples):
        module = types.ModuleType(f"docs_sample_{number}")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        # Blank lines in front put each line of code at its line in the file.
        code = compile("\n" * (sample.line - 1) + sample.code, sample.file, "exec")
        try:
            exec(code, module.__dict__)  # noqa: S102 - the docs' own samples
        except RequestSentError:
            pass
        except Exception as error:  # noqa: BLE001 - any error is the sample's
            frames = traceback.extract_tb(error.__traceback__)
            line = [frame.lineno for frame in frames if frame.filename == sample.file][-1]
            errors.append(f"{sample.file}:{line}: {type(error).__name__}: {error}")
    return errors


def test_the_samples_in_the_docs_type_check(tmp_path: Path) -> None:
    samples = [sample for name in CHECKED for sample in samples_in(ROOT / name, name)]
    assert type_errors(samples, tmp_path) == []


def test_the_samples_in_the_docs_run(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [sample for name in CHECKED for sample in samples_in(ROOT / name, name)]
    assert run_errors(samples, monkeypatch) == []


def test_the_check_reports_errors_at_their_line_in_the_page(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "\n".join(
            [
                "# A page",  # 1
                "```bash",
                "pip install clientx",
                "```",
                "```python",  # 5
                "from clientx import ClientX",
                "",
                "print(ClientX)",
                "```",
                "```python no-check",  # 10
                "from clientx import Missing",
                "```",
                "- In a list item:",
                "",
                "  ```python",  # 15
                "  from clientx import NotThere",
                "  ```",
                "```python",
                "def handler(request): ...",  # 19: strict wants annotations.
                "```",
            ]
        )
    )
    checked = tmp_path / "checked"
    checked.mkdir()

    errors = type_errors(samples_in(page, "page.md"), checked)

    # None from the good block (lines 6 to 8), the no-check one (11) or bash.
    assert {error.split(":", 2)[1] for error in errors} == {"16", "19"}
    assert 'page.md:16: "NotThere" is unknown import symbol' in errors
    assert 'page.md:19: Type annotation is missing for parameter "request"' in errors


def test_the_run_reports_errors_at_their_line_in_the_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "\n".join(
            [
                "```python",  # 1
                "from clientx import ClientX, method",
                "",
                "class API(ClientX):",  # 4: endpoints are planned here.
                "    @method.get('/items')",
                "    def items(self, page: int) -> None: ...",
                "```",
                "```python",
                "from clientx import ClientX, method",
                "",  # 10
                "class API(ClientX):",
                "    @method.get('/items')",
                "    def items(self) -> None: ...",
                "",
                "API('https://api.example.com').items()",  # 15: stops here.
                "raise AssertionError('not reached')",
                "```",
            ]
        )
    )

    errors = run_errors(samples_in(page, "page.md"), monkeypatch)

    [error] = errors
    assert error.startswith("page.md:4: DefinitionError: Endpoint 'API.items': Parameter 'page' needs a helper")


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
