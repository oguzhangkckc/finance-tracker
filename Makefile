RUN := uv run --frozen

.PHONY: sync fmt lint typecheck imports test live audit check deploy-py312 openapi frontend frontend-node

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

check: lint typecheck imports test frontend

# K-139: Biome, tsc, Vitest, şemadan üretilen tiplerin farkı ve derleme.
frontend: frontend-node frontend/node_modules/.package-lock.json
	cd frontend && npm run check

# npm ci yalnız kilit dosyası ya da Node sürümü değişince yeniden çalışır.
frontend/node_modules/.package-lock.json: frontend/package-lock.json frontend/.nvmrc
	cd frontend && npm ci

frontend-node:
	@want=$$(cut -d. -f1 frontend/.nvmrc); have=$$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null); \
	if [ "$$want" != "$$have" ]; then \
		echo "Node $$want gerekli (bulunan: $${have:-yok}); frontend/ içinde 'nvm use' ile seç." >&2; exit 1; \
	fi

# Pi'nin sistem Python'u 3.12; finans-guncelle ve testleri onunla da çalışmalı (K-140).
deploy-py312:
	uv run --python 3.12 --no-project python -I -m py_compile deploy/guncelle.py
	uv run --python 3.12 --no-project --with pytest==9.2.0 pytest --confcutdir=tests/deploy_guncelle tests/deploy_guncelle

# API şeması repodadır ve TypeScript tiplerinin kaynağıdır; bir test eşitliğini denetler (K-138).
openapi: frontend-node frontend/node_modules/.package-lock.json
	$(RUN) python -m finans.api.openapi > frontend/src/api/openapi.json
	cd frontend && npm run types
