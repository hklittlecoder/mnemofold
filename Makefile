PYTHON = .venv/bin/python

.PHONY: build test format-check format lint test-all typecheck release clean

build:
	$(PYTHON) -m build --wheel --no-isolation

test:
	$(PYTHON) -m pytest -q -m "not slow"

format-check:
	$(PYTHON) -m ruff format --check src tests examples scripts
	$(PYTHON) -m ruff check src tests examples scripts

format:
	$(PYTHON) -m ruff check --fix --unsafe-fixes src tests examples scripts
	$(PYTHON) -m ruff format src tests examples scripts

lint:
	$(PYTHON) -m ruff check src tests examples scripts
	$(PYTHON) -m mypy src/mnemofold

test-all:
	$(PYTHON) -m pytest -q

typecheck:
	$(PYTHON) -m mypy src/mnemofold

release: build
	@echo "Built wheel in dist/"

clean:
	rm -rf dist build src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
