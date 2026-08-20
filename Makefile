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
	@echo "  make restore-local [--segment cm] pull pruned files back from B2"
	@echo "  make prune-local [DRY=1]"
	@echo "                    delete local files B2 has confirmed (frees disk)"
	@echo "  make build-master   build and persist the security master from B2"
	@echo "  make test-lookahead the adversarial firewall suite"
	@echo "  make provenance   show which data is point-in-time and which is not"
	@echo "  make check-master   security master acceptance checks"
	@echo "  make sync-supervisor  keep the mirror complete, restart sync if it dies"
	@echo "  make sync-until-complete"
	@echo "                    loop sync until every tree is mirrored, then prune"
	@echo "  make sync-and-prune"
	@echo "                    sync then prune - the normal way to run these two"
	@echo "  make ingest-fundamentals [LIMIT=n]"
	@echo "                    fetch screener.in fundamentals for the universe"
	@echo "  make ingest-corp-actions [FROM_YEAR=2015] [TO_YEAR=2026]"
	@echo "                    fetch NSE dividends, bonuses, splits, rights"
	@echo "  make check-costs    transaction cost model acceptance checks"
	@echo "  make check-adjust   adjustment engine acceptance checks"
	@echo "  make reconcile [DAYS=n]  bhavcopy vs Kite minute bars, two vendors"
	@echo "  make quality-options [DAYS=n] [UNDERLYING=NIFTY]"
	@echo "                    option-chain no-arbitrage checks"
	@echo "  make quality [ROWS=n] [LIMIT=n]"
	@echo "                    data quality report; ROWS=n also checks price rows"
	@echo "  make research [CRITIC=H-0002]  the loop: cards, critic, gate verdicts"
	@echo "  make scout [PROPOSE=n]   what would searching cost? then draft cards"
	@echo "  make gate-acceptance    feed the gate 3 overfit strategies; all must die"
	@echo "  make gate H=H-0001      apply the mandate; PROMOTE or KILL"
	@echo "  make validate H=H-0001  overfitting battery: CPCV, DSR, PBO, MinBTL"
	@echo "  make test-engine    engine self-tests  <- the most important gate"
	@echo "  make backtest STRAT=rank FEATURE=momentum_12_1"
	@echo "                    Tier B event-driven + reconciliation against Tier A"
	@echo "  make backtest-fast STRAT=rank FEATURE=momentum_12_1 [COMPARE=1]"
	@echo "                    Tier A vectorised backtest (screening only)"
	@echo "  make ic FEATURE=momentum_12_1 [HORIZON=21] [ALL=1]"
	@echo "                    information coefficient tear sheet"
	@echo "  make build-panel [FROM=2023-01-01]  adjusted price panel for features"
	@echo "  make build-factors  build price + total-return adjustment factors"
	@echo "                    (cached and resumable; see RUNBOOKS/b2-transaction-cap.md)"
	@echo "  make daily        refresh everything + sync + prune (schedulable)"

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

restore-local:
	uv run python -m eulerlab.ingest.restore_local $(ARGS)

prune-local:
	uv run python -m eulerlab.ingest.prune_local $(if $(DRY),--dry-run,)

build-master:
	uv run python -m eulerlab.master.build_master $(if $(DAILY),--cadence daily,)

provenance:
	@uv run python -m eulerlab.bitemporal.provenance $(if $(MANIFEST),--manifest $(MANIFEST),)

test-lookahead:
	@uv run pytest tests/test_lookahead.py tests/test_provenance.py tests/test_survivorship.py --no-header -q

check-master:
	@uv run python -m eulerlab.master.check

sync-until-complete:
	@./tools/sync_until_complete.sh

sync-supervisor:
	@./tools/sync_supervisor.sh

sync-and-prune: sync-cloud prune-local

ingest-fundamentals:
	uv run python -m eulerlab.fundamentals.backfill $(if $(LIMIT),--limit $(LIMIT),)

ingest-corp-actions:
	uv run python -m eulerlab.corp_actions.feed $(if $(FROM_YEAR),--from-year $(FROM_YEAR),) $(if $(TO_YEAR),--to-year $(TO_YEAR),)

reconcile:
	@uv run python -m eulerlab.quality.reconcile_run $(if $(DAYS),--days $(DAYS),) $(if $(SYMBOLS),--symbols $(SYMBOLS),)

quality-options:
	@uv run python -m eulerlab.options.run $(if $(DAYS),--days $(DAYS),) $(if $(UNDERLYING),--underlying $(UNDERLYING),) $(if $(UNTRADED),--include-untraded,)

quality:
	@uv run python -m eulerlab.quality.run $(if $(ROWS),--rows $(ROWS),) $(if $(LIMIT),--limit $(LIMIT),) $(if $(SUPPRESSED),--show-suppressed,)

check-costs:
	@uv run python -m eulerlab.costs.check

check-adjust:
	@uv run python -m eulerlab.corp_actions.check

research:
	@uv run python -m eulerlab.research.orchestrator $(if $(CRITIC),--critic $(CRITIC),) $(if $(LIBRARY),--library,)

scout:
	@uv run python -m eulerlab.research.scout $(if $(PROPOSE),--propose $(PROPOSE),) $(if $(DRAFT),--draft "$(DRAFT)",) $(if $(SOURCE),--source $(SOURCE),)

gate-acceptance:
	@uv run python -m eulerlab.validation.gate_acceptance $(if $(SYMBOLS),--symbols $(SYMBOLS),)

gate:
	@uv run python -m eulerlab.gate_run $(if $(H),--hypothesis $(H),) $(if $(READ_HOLDOUT),--read-holdout $(READ_HOLDOUT),)

validate:
	@uv run python -m eulerlab.validation.run $(if $(H),--hypothesis $(H),)

test-engine:
	@uv run python -m eulerlab.backtest.selftest $(if $(UPDATE),--update-golden,)

backtest:
	@uv run python -m eulerlab.backtest.compare $(if $(STRAT),--strategy $(STRAT),) $(if $(FEATURE),--feature $(FEATURE),) $(if $(REBALANCE),--rebalance $(REBALANCE),) $(if $(MIN_TURNOVER),--min-turnover $(MIN_TURNOVER),)

backtest-fast:
	@uv run python -m eulerlab.backtest.report $(if $(STRAT),--strategy $(STRAT),) $(if $(FEATURE),--feature $(FEATURE),) $(if $(REBALANCE),--rebalance $(REBALANCE),) $(if $(MIN_TURNOVER),--min-turnover $(MIN_TURNOVER),) $(if $(COMPARE),--compare,)

ic:
	@uv run python -m eulerlab.features.tearsheet $(if $(FEATURE),--feature $(FEATURE),) $(if $(HORIZON),--horizon $(HORIZON),) $(if $(ALL),--all,)

build-panel:
	@uv run python -m eulerlab.features.build_panel $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),)

build-factors:
	uv run python -m eulerlab.corp_actions.build_factors $(if $(LIMIT_FILES),--limit-files $(LIMIT_FILES),)

# One command to keep every dataset current, safe to schedule. Each step is
# idempotent: already-current data costs nothing, so re-running is cheap and
# a missed day self-heals on the next run.
daily:
	@echo "== EOD bhavcopy =="
	-uv run python -m eulerlab.ingest.nse_eod --from $$(date -v-7d +%Y-%m-%d)
	@echo "== participant OI =="
	-uv run python -m eulerlab.ingest.backfill_oi --from $$(date -v-7d +%Y-%m-%d)
	@echo "== fundamentals =="
	-uv run python -m eulerlab.fundamentals.backfill
	@echo "== sync and prune =="
	$(MAKE) sync-cloud
	$(MAKE) prune-local
