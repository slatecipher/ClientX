.PHONY: lint lint-ci typecheck typecheck-tests test test-ci check

lint:
	uv run ruff format src test
	uv run ruff check --fix src test

lint-ci:
	uv run ruff format --check src test
	uv run ruff check src test

# Gates CI. Paths on the command line override `include` in pyproject.toml,
# so this stays scoped to the shipped package even though `include` is wider.
# test/test_typing.py is the static typing contract for decorated endpoints,
# so it gates alongside src rather than riding the advisory test check.
typecheck:
	uv run pyright src test/test_typing.py

# Advisory: reported in CI via continue-on-error, never blocks a merge.
typecheck-tests:
	uv run pyright test

test:
	uv run pytest

test-ci:
	uv run pytest --cov=clientx --cov-report=term-missing

check: lint typecheck test