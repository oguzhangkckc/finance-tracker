RUN := uv run --frozen

.PHONY: sync fmt lint typecheck imports test live audit check

sync:
	uv sync --locked

fmt:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

lint:
	$(RUN) ruff format --check .
	$(RUN) ruff check .

typecheck:
	$(RUN) mypy

imports:
	$(RUN) lint-imports

test:
	$(RUN) pytest --cov --cov-report=term-missing
	$(RUN) coverage report --include='src/finans/domain/*' --fail-under=95 --skip-covered

live:
	$(RUN) pytest -m live

audit:
	@tmp=$$(mktemp) && trap 'rm -f "$$tmp"' EXIT && \
	uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file "$$tmp" >/dev/null && \
	$(RUN) pip-audit --strict --disable-pip --require-hashes --requirement "$$tmp"

check: lint typecheck imports test
