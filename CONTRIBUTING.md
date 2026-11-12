# Contributing to ClientX

Thanks for your interest in ClientX. It's a personal project maintained in spare time, so replies to issues and pull requests may take a while.

## Issues

- **Bugs:** include a minimal example that reproduces the problem, what you expected to happen, and your versions of Python, `clientx`, `httpx2` and `pydantic`.
- **Features:** describe the use case first, then the solution you have in mind.

For anything bigger than a small fix, please open an issue to discuss it before you start on a pull request.

To report a security vulnerability, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). Fork the repository, clone your fork, and run:

```bash
uv sync --all-groups --reinstall-package clientx
make check   # lint, type check, and tests
```

The package is installed as a regular wheel, not in editable mode. If your changes to `src/` don't show up, run the `uv sync` command again.

Other useful commands:

```bash
make lint                                       # format and auto-fix with ruff
make typecheck                                  # pyright (strict on src/), and pyright and mypy on the typing contract
uv run pytest test/test_clientx.py::test_name   # run a single test
```

When you change code:

- New code in `src/` needs complete type annotations. Pyright checks `src/` in strict mode.
- `test/test_typing.py` checks that decorated endpoints keep their signatures for type checkers, under both pyright and mypy. Update it if you change the decorators or other public signatures, and mark each call that must be rejected for both checkers: `# type: ignore[code]  # pyright: ignore[rule]`.
- Add tests for new behavior and for bug fixes. `make test` prints a coverage report.
- In tests that send requests, take the `mock_transport` fixture from `test/conftest.py` as a parameter: it records what's sent and answers without a network. pytest runs in its recommended `importlib` import mode, where test modules can't import helper modules, so share test helpers as fixtures in `conftest.py`. It also runs in strict mode: an unregistered marker or a duplicate parametrize ID is an error.
- Ruff formats and lints the code with a 120-character line limit. `make lint` fixes most issues for you.

## Pull requests

- Keep each pull request to one change, on a branch named `<type>/<short-description>`, for example `fix/stream-close`.
- In the description, say what changed and why, and how you tested it. If the pull request resolves an issue, add `Closes #N`.
- For changes users will notice, add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md), and update [README.md](README.md) and [llms.txt](llms.txt) if they describe the behavior.
- CI must pass: lint, type check, and tests on Python 3.12 to 3.14 and on the lowest supported dependency versions.
- Pull requests are squash-merged, so each one becomes a single commit on `mainline`. That commit's subject comes from the pull request title, or from the commit subject when there is only one commit. Use the format below for both.

## Commit messages

A subject line, a blank line, then a bullet list of the changes. Put any note, such as "No behavior changes", as the last bullet.

```
<type>: <Summary in the imperative, capitalized, no period>

- First change
- Second change
- Note
```

For example:

```
fix: Always release the connection for streamed responses

- Close the response when a stream decoder's iterator finishes, fails,
  or is abandoned.
- Also close it if the decoder raises before returning an iterator.
- No change for endpoints that don't stream.
```

| Type | Use for | Label |
|---|---|---|
| `feat` | New features and public API | `enhancement` |
| `fix` | Bug fixes | `bug` |
| `docs` | Documentation only | `documentation` |
| `refactor` | Internal changes with no change in behavior | `refactor` |
| `ci` | GitHub Actions workflows and Dependabot configuration | `ci` |
| `chore` | Packaging, tooling, and dependency updates | `maintenance` |

The maintainer applies the labels. Two more labels mark special cases:

- `breaking change`: the change can break code that uses ClientX. Say so in the pull request description and in the changelog entry.
- `release`: preparing or publishing a release.

Dependabot's update pull requests get the `dependencies` label automatically.

## Releasing (maintainer)

`.github/workflows/release.yml` publishes to PyPI with Trusted Publishing, so no API tokens are stored.

1. Open a release pull request that sets `version` in `pyproject.toml`, runs `uv lock`, and renames `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`. Merge it.
2. Optional dry run: run the Release workflow manually with `gh workflow run release.yml`. It builds the package and publishes to TestPyPI only.
3. Publish a GitHub release tagged `vX.Y.Z` on `mainline`, for example `gh release create vX.Y.Z --target mainline --title vX.Y.Z --notes "..."`. The workflow checks that the tag matches the project version, builds and smoke-tests the package, then publishes to TestPyPI and PyPI.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
