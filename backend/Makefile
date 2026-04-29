install:
	uv sync

dev:
	uv run langgraph dev --no-browser --no-reload --n-jobs-per-worker 10

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload --reload-dir app --reload-dir packages/harness/deerflow

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uvx ruff check .
	uvx ruff format --check .

format:
	uvx ruff check . --fix && uvx ruff format .
