.PHONY: test fmt lint all

test:
	uv run pytest --ignore=tests/browser
	uv run pytest tests/browser

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests

all: fmt lint test
