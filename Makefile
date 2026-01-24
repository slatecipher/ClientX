.PHONY: lint lint-ci test test-ci check

lint:
	uv run ruff format src test
	uv run ruff check --fix src test

lint-ci:
	uv run ruff format --check src test
	uv run ruff check src test

test:
	uv run pytest

test-ci:
	uv run pytest --cov=clientx --cov-report=term-missing

check: lint test