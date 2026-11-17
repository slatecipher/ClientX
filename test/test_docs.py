"""Code samples in the docs type-check under pyright's strict mode.

Each ```python block in a checked file is type-checked on its own, so it must
carry its own imports, as a reader copying it would need. A block that's
deliberately incomplete is fenced as ```python no-check: GitHub still
highlights it as Python, since it reads only the first word.
"""

import json
import re
import subprocess  # noqa: S404 - runs pyright on the docs' own samples
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# The files whose samples are checked. Each page joins this list in the commit
# that rewrites it. Once every page is rewritten, the list goes, and every
# Markdown file in docs/, README.md and llms.txt is checked.
CHECKED: list[str] = []

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


def test_the_samples_in_the_docs_type_check(tmp_path: Path) -> None:
    samples = [sample for name in CHECKED for sample in samples_in(ROOT / name, name)]
    if not samples:
        pytest.skip("No page is checked yet: CHECKED is empty.")
    assert type_errors(samples, tmp_path) == []


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
