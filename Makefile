# Pedigree Makefile — targets work on Windows and Linux (ADR-003).
# On Windows the venv python is .venv/Scripts/python.exe; elsewhere .venv/bin/python.
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

.DEFAULT_GOAL := help
.PHONY: help setup start-db stop-db db-status test test-quick lint check eval eval-quick demo seed clean-clone

help:
	@echo "Pedigree targets:"
	@echo "  make setup       create .venv and install the package + dev deps"
	@echo "  make start-db    start FalkorDB v4.22.1 (Docker image, or pinned .so on Linux)"
	@echo "  make stop-db     stop the local FalkorDB"
	@echo "  make db-status   show DB reachability and module version"
	@echo "  make test        full test suite (skips nothing)"
	@echo "  make test-quick  fast subset (deselects slow tests)"
	@echo "  make lint        ruff check"
	@echo "  make check       lint + test-quick + secret scan + numbers check"
	@echo "  make eval        full evaluation run (writes evals/results/*.csv)"
	@echo "  make eval-quick  2-minute evaluation subset"
	@echo "  make demo        seed the demo tenant (synthetic scenarios S1+S8)"
	@echo "  make seed        alias for demo"

setup:
	uv venv --python 3.12 .venv 2>/dev/null || python -m venv .venv
	uv pip install --python $(PY) -e ".[dev]" 2>/dev/null || $(PY) -m pip install -e ".[dev]"
	@echo "setup done. Python: $$($(PY) --version)"

start-db:
	$(PY) -m pedigree.cli db start

stop-db:
	$(PY) -m pedigree.cli db stop

db-status:
	$(PY) -m pedigree.cli db status

test:
	$(PY) -m pytest -q

test-quick:
	$(PY) -m pytest -q -m "not slow"

lint:
	$(PY) -m ruff check .

check: lint test-quick
	$(PY) scripts/secret_scan.py
	$(PY) scripts/check_numbers.py

eval:
	$(PY) evals/run_all.py

eval-quick:
	$(PY) evals/run_all.py --quick

demo seed:
	$(PY) scripts/seed_demo.py

clean-clone:
	bash scripts/clean_clone_check.sh
