# Pedigree Makefile — targets work on Windows and Linux (ADR-003).
# On Windows the venv python is .venv/Scripts/python.exe; elsewhere .venv/bin/python.
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

.DEFAULT_GOAL := help
.PHONY: help setup start-db stop-db db-status test test-quick lint check check-perf eval eval-quick demo seed clean-clone dogfood dogfood-strict

help:
	@echo "Pedigree targets:"
	@echo "  make setup       create .venv and install the package + dev deps"
	@echo "  make quickstart  Linux no-Docker: locked install, pinned DB module, seed, serve"
	@echo "  make quickstart-windows  Windows: locked install + owned Docker DB, seed, serve"
	@echo "  make start-db    start FalkorDB v4.22.1 (Docker image, or pinned .so on Linux)"
	@echo "  make stop-db     stop the local FalkorDB"
	@echo "  make db-status   show DB reachability and module version"
	@echo "  make test        full test suite (skips nothing)"
	@echo "  make test-quick  fast subset (deselects slow and perf tests)"
	@echo "  make lint        ruff check"
	@echo "  make check       lint + test-quick + secret scan + numbers + readme check"
	@echo "  make check-perf  heavy perf gates on the live DB (P-010)"
	@echo "  make eval        full evaluation run (writes evals/results/*.csv)"
	@echo "  make eval-quick  2-minute evaluation subset"
	@echo "  make demo        seed the demo tenant (synthetic scenarios S1+S8)"
	@echo "  make seed        alias for demo"
	@echo "  make dogfood     brutal end-to-end user pass (spawns a server; writes scratch/dogfood/)"
	@echo "  make dogfood-strict  same, but every expected-failure must now pass"

setup:
	uv sync --frozen --extra dev
	uv lock --check

quickstart:
	bash scripts/quickstart.sh

quickstart-windows:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quickstart-windows.ps1

start-db:
	$(PY) -m pedigree.cli db start

stop-db:
	$(PY) -m pedigree.cli db stop

db-status:
	$(PY) -m pedigree.cli db status

test:
	$(PY) -m pytest -q

test-quick:
	$(PY) -m pytest -q -m "not slow and not perf"

lint:
	$(PY) -m ruff check .

check: lint test-quick
	$(PY) scripts/secret_scan.py
	$(PY) scripts/check_numbers.py
	$(PY) scripts/check_readme.py

check-perf:
	$(PY) -m pytest -q -m "perf"

eval:
	$(PY) evals/run_all.py

eval-quick:
	$(PY) evals/run_all.py --quick

demo seed:
	$(PY) scripts/seed_demo.py

clean-clone:
	bash scripts/clean_clone_check.sh

dogfood:
	$(PY) scripts/dogfood.py

dogfood-strict:
	$(PY) scripts/dogfood.py --strict
