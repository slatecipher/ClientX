.PHONY: lint lint-ci typecheck test test-ci check

lint:
	uv run ruff format src test
	uv run ruff check --fix src test

lint-ci:
	uv run ruff format --check src test
	uv run ruff check src test

typecheck:
	uv run pyright

test:
	uv run pytest

test-ci:
	uv run pytest --cov=clientx --cov-report=term-missing

check: lint typecheck test