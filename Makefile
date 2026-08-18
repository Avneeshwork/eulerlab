.DEFAULT_GOAL := help

.PHONY: help install verify test lint fmt types docs-check state

help:
	@echo "EulerLab — targets"
	@echo ""
	@echo "  make install      create the venv and install pre-commit hooks (once)"
	@echo "  make verify       run every gate and print the table   <- the one you need"
	@echo "  make test         pytest only"
	@echo "  make lint         ruff check + format check"
	@echo "  make fmt          apply ruff fixes and formatting"
	@echo "  make types        mypy --strict"
	@echo "  make docs-check   fail if src/ changed without docs"
	@echo "  make state        print where the project is"
	@echo ""
	@echo "  make ingest-eod FROM=2015-01-01 [TO=YYYY-MM-DD]"
	@echo "                    download NSE equity + F&O bhavcopy into data/landing/"
	@echo "  make check-landing  re-hash every landed file; proves nothing changed"
	@echo "  make kite-login   obtain a Kite access token (expires 6 AM daily)"
	@echo "  make ingest-oi FROM=2020-01-01 [TO=...]"
	@echo "                    backfill NSE participant-wise F&O open interest"
	@echo "  make ingest-minute [YEARS=5] [LIMIT=n]"
	@echo "                    backfill 1-minute candles for config/universe_top250.txt"
	@echo "  make sync-cloud [DRY=1] [VERIFY=1]"
	@echo "                    mirror the landing zone to Backblaze B2"

install:
	uv sync --extra dev
	uv run pre-commit install

verify:
	@uv run python tools/verify.py

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

types:
	uv run mypy

docs-check:
	uv run python tools/docs_check.py

state:
	@uv run python tools/state.py

ingest-eod:
	@test -n "$(FROM)" || (echo "usage: make ingest-eod FROM=2015-01-01 [TO=2026-08-18]"; exit 2)
	uv run python -m eulerlab.ingest.nse_eod --from $(FROM) $(if $(TO),--to $(TO),)

check-landing:
	@uv run python -m eulerlab.ingest.verify_landing

kite-login:
	@uv run python -m eulerlab.broker.kite_login

ingest-oi:
	@test -n "$(FROM)" || (echo "usage: make ingest-oi FROM=2020-01-01 [TO=2026-08-18]"; exit 2)
	uv run python -m eulerlab.ingest.backfill_oi --from $(FROM) $(if $(TO),--to $(TO),)

ingest-minute:
	uv run python -m eulerlab.ingest.backfill_minute $(if $(YEARS),--years $(YEARS),) $(if $(LIMIT),--limit $(LIMIT),)

sync-cloud:
	uv run python -m eulerlab.ingest.sync_cloud $(if $(DRY),--dry-run,) $(if $(VERIFY),--verify,)
