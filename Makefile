.PHONY: install test lint format doctor package

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

doctor:
	./cipher doctor

package:
	./cipher alexa package
