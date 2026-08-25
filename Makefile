.DEFAULT_GOAL := help

.PHONY: help install verify test lint fmt types docs-check state acceptance montecarlo chaos paper api ui workbench attribution kill-status kill-stop reconcile-book

help:
	@echo "EulerLab — targets"
	@echo ""
	@echo "  make install      create the venv and install pre-commit hooks (once)"
	@echo "  make verify       run every gate and print the table   <- the one you need"
	@echo "  make acceptance [ALL=1]  every sprint's capability, on the real data"
	@echo ""
	@echo "  -- the workbench --"
	@echo "  make api          start the strategy API on :8000"
	@echo "  make ui           start the web interface on :3000 (needs make api)"
	@echo "  make workbench    both at once"
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
	@echo ""
	@echo "  -- order path (sprints 19-28) --"
	@echo "  make tweezer [UNIVERSE=nifty50|nifty100|nifty250] [DAY=YYYY-MM-DD]"
	@echo "                    intraday Tweezer Bottom scan; defaults to nifty50"
	@echo "  make montecarlo [FEATURE=... DAYS=n]  drawdown path risk + Sharpe interval"
	@echo "  make chaos        kill it mid-order and check it tells the truth"
	@echo "  make kill-status  is the kill switch tripped, and why"
	@echo "  make kill-stop REASON=\"...\"   stop trading now"
	@echo "  make paper [FEATURE=... DAYS=n SLIPPAGE=25]"
	@echo "                    run a strategy through the OMS against a paper broker"
	@echo "  make attribution [FRICTIONLESS=1]"
	@echo "                    reality gap: paper vs the backtest that authorised it"
	@echo "  make reconcile-book  broker positions vs ours; the broker wins"
	@echo ""
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
api:
	uv run --extra web uvicorn eulerlab.api.server:app --port 8000 --reload

ui:
	cd web && npm install --silent && npm run dev

workbench:
	@echo "starting the API on :8000 and the UI on :3000"
	@$(MAKE) -j2 api ui

acceptance:
	@uv run python tools/acceptance.py $(if $(ALL),--all,)

tweezer:
	@uv run python -m eulerlab.intraday.scan $(if $(UNIVERSE),--universe $(UNIVERSE),$(if $(SYMBOLS),,--universe nifty50)) $(if $(SYMBOLS),--symbols $(SYMBOLS),) $(if $(DAY),--day $(DAY),) $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),) $(if $(WORKERS),--workers $(WORKERS),) $(if $(QUIET),--quiet,) $(if $(PRUNE),--prune,)

montecarlo:
	@uv run python -m eulerlab.validation.montecarlo_run $(if $(FEATURE),--feature $(FEATURE),) $(if $(DAYS),--days $(DAYS),) $(if $(SIMS),--simulations $(SIMS),)

chaos:
	@uv run python -m eulerlab.oms.chaos

kill-status:
	@uv run python -m eulerlab.oms.killswitch

kill-stop:
	@test -n "$(REASON)" || (echo 'usage: make kill-stop REASON="why"'; exit 2)
	@uv run python -m eulerlab.oms.killswitch --trip "$(REASON)"

paper:
	@uv run python -m eulerlab.paper.runner $(if $(FEATURE),--feature $(FEATURE),) $(if $(DAYS),--days $(DAYS),) $(if $(SLIPPAGE),--slippage-bps $(SLIPPAGE),) $(if $(TOP_N),--top-n $(TOP_N),) $(if $(RESET),--reset,)

attribution:
	@uv run python -m eulerlab.paper.attribution $(if $(FEATURE),--feature $(FEATURE),) $(if $(DAYS),--days $(DAYS),) $(if $(SLIPPAGE),--slippage-bps $(SLIPPAGE),) $(if $(FRICTIONLESS),--frictionless,)

reconcile-book:
	@uv run python -m eulerlab.oms.book

# Is the Kite token from today, or from a day the market has since moved past?
#
# The token expires at 6 AM and reminting it needs an interactive login, so an
# unattended job cannot renew it. Checking first turns "the minute ingest
# silently did nothing" into a line in the log that names the cause — which is
# the difference between noticing on the day and noticing in a month.
kite-fresh:
	@uv run python -c "import datetime as d, sys; from eulerlab.broker.kite_session import load; s = load(); 	  sys.exit(0) if s and d.datetime.fromisoformat(s.minted_at).date() == d.datetime.now(d.UTC).date() 	  else (print('kite token is stale or absent - run: make kite-login'), sys.exit(1))"

# Minute bars for the last few sessions. NOT a backfill: --years 5 is a one-off
# of ~13,500 chunks, this keeps the tail current.
daily-minute:
	@$(MAKE) --no-print-directory kite-fresh && 	  uv run python -m eulerlab.ingest.backfill_minute --years 1 $(if $(LIMIT),--limit $(LIMIT),)

daily:
	@echo "== EOD bhavcopy =="
	-uv run python -m eulerlab.ingest.nse_eod --from $$(date -v-7d +%Y-%m-%d)
	@echo "== participant OI =="
	-uv run python -m eulerlab.ingest.backfill_oi --from $$(date -v-7d +%Y-%m-%d)
	@echo "== fundamentals =="
	-uv run python -m eulerlab.fundamentals.backfill
	@echo "== mutual fund NAVs =="
	-uv run python -m eulerlab.ingest.mf_backfill --snapshot-only
	@echo "== economic calendar =="
	-uv run python -m eulerlab.ingest.forexfactory
	@echo "== minute bars (needs a token minted today) =="
	-$(MAKE) --no-print-directory daily-minute
	@echo "== crypto (Binance public archive, no auth) =="
	-uv run python -m eulerlab.ingest.crypto_backfill --years 1
	@echo "== crypto month-end gap (Binance daily archive) =="
	-uv run python -m eulerlab.ingest.crypto_fill
	@echo "== FX (FXCM weekly candles) =="
	-uv run python -m eulerlab.ingest.fx_bulk_backfill --from-year $$(date +%Y)
	@echo "== per-instrument news (equity, crypto, FX) =="
	-uv run python -m eulerlab.ingest.news
	@echo "== index levels, movers, sectors =="
	-uv run python -m eulerlab.indices
	@echo "== US bars, actions, news =="
	-uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); alpaca.land_bars(s, start='2016-01-01'); alpaca.land_actions(s, start='2016-01-01'); alpaca.land_news(s, start='2026-06-01')"
	@echo "== US panel =="
	-$(MAKE) --no-print-directory build-us-panel
	@echo "== sync and prune =="
	$(MAKE) sync-cloud
	@echo "== price panel =="
	-$(MAKE) --no-print-directory build-panel
	$(MAKE) prune-local
	@echo "== landing census =="
	-$(MAKE) --no-print-directory manifest

# Mutual fund NAVs. --snapshot-only is what `daily` runs (one request, the
# whole universe); the full history backfill is ~14,000 requests and is a
# one-off, so it is not in the daily path.
mf-ingest:
	@uv run python -m eulerlab.ingest.mf_backfill $(if $(SNAPSHOT),--snapshot-only,) $(if $(LIMIT),--limit $(LIMIT),) $(if $(PACE),--pace $(PACE),)

# Morningstar star / medalist ratings — the one thing AMFI does not publish.
# Reports how far the name-based join to AMFI reaches, every run, because that
# compromise should stay visible (ADR-039).
morningstar:
	@uv run python -m eulerlab.ingest.morningstar_run $(if $(PACE),--pace $(PACE),) $(if $(NOJOIN),--no-join,)

# Minute-level crypto from Binance's bulk archive. NOT ccxt: five years of 1m
# bars for 20 coins is ~52,000 paginated REST calls versus ~1,200 monthly ZIPs.
# FX minute bars from Dukascopy's public tick feed. Resumable: a day already on
# disk costs no requests, so run it repeatedly rather than once for ten years.
fx:
	@uv run python -m eulerlab.ingest.fx_backfill $(if $(PAIRS),--pairs $(PAIRS),) $(if $(YEARS),--years $(YEARS),) $(if $(PACE),--pace $(PACE),) $(if $(LIMIT),--limit $(LIMIT),)

# FX in bulk from FXCM's weekly candle files. This is the backfill path; `make
# fx` (Dukascopy, per hour) is 100x slower and kept only as a second opinion.
# Sector, market cap and headline ratios, reduced from the fundamentals tree to
# one small JSON. 2,353 Parquet files is far too slow for a screen that should
# feel instant.
# The ForexFactory weekly calendar. History has to be accumulated - the feed
# publishes one week and has no past endpoint - so this runs daily and merges.
calendar:
	@uv run python -m eulerlab.ingest.forexfactory

news:
	@uv run python -m eulerlab.ingest.news

# Counts every landing tree once, so the capability matrix never lists the
# bucket to render. Runs at the end of `daily`, after the sync has settled.
# One sweep of index levels, movers and sector performance. Landed rather than
# fetched per page render: a sweep is 29 FMP calls against a 250/day free
# budget, so rendering it live would spend the day's allowance before lunch.
# Fills the window the monthly archive does not cover yet. Binance publishes
# months after they end, so without this the corpus stops at the last
# month-end however often the backfill runs.
crypto-fill:
	@uv run python -m eulerlab.ingest.crypto_fill $(if $(SINCE),--since=$(SINCE),)

# US market data from Alpaca. The S&P snapshot is landed dated and used for
# labelling only — ADR-008 rejects published index membership for selecting a
# backtest universe, because today's list applied across history drops
# everything that was removed.
us-sp500:
	@uv run python -c "from eulerlab.ingest import alpaca; n,e=alpaca.land_sp500(); print(f'{n} constituents{chr(32)}{e}')"

us-bars:
	@uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); w,n,e=alpaca.land_bars(s, start='$(FROM)' or '2016-01-01'); print(f'{w} symbols, {n:,} bars {e}')"

# Fetch, sync and prune a batch at a time: the full window is ~3 GB against
# ~4 GB of free disk, so landing it all and syncing afterwards would run out.
us-minute:
	@uv run python -m eulerlab.ingest.us_minute $(if $(LIMIT),--limit $(LIMIT),) $(if $(FROM),--start $(FROM),) $(if $(BATCH),--batch $(BATCH),)

# Delta's own candles. Held even though the venue difference is immaterial —
# measured 2026-08-25, Delta's BTCUSD perpetual and Binance's BTCUSDT spot
# agree within 0.026% on daily closes against a 0.118% round-trip fee.
delta-candles:
	@uv run python -c "from eulerlab.ingest import delta; n,e=delta.land_candles(); print(f'{n:,} rows {e}')"

# The derived US panel the snapshot reads. Built once from the landed bars —
# 36,446 monthly files live in B2, and touching them per request is the
# mistake this platform has made twice already.
build-us-panel:
	@uv run python -m eulerlab.features.us_panel

us-actions:
	@uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); n,e=alpaca.land_actions(s, start='2016-01-01'); print(f'{n:,} rows {e}')"

us-news:
	@uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); n,e=alpaca.land_news(s, start='2026-06-01'); print(f'{n:,} rows {e}')"

world:
	@uv run python -m eulerlab.indices

manifest:
	@uv run python -m eulerlab.ingest.manifest

fmp-probe:
	@uv run python -m eulerlab.ingest.fmp --probe

fmp-news:
	@uv run python -m eulerlab.ingest.fmp

company-digest:
	@uv run python -c "from eulerlab.features import company; d=company.build_digest(); p=company.save_digest(d); print(f'{len(d):,} companies -> {p}')"

fx-bulk:
	@uv run python -m eulerlab.ingest.fx_bulk_backfill $(if $(PAIRS),--pairs $(PAIRS),) $(if $(FROM),--from-year $(FROM),) $(if $(TO),--to-year $(TO),)

crypto:
	@uv run python -m eulerlab.ingest.crypto_backfill $(if $(COINS),--coins $(COINS),) $(if $(YEARS),--years $(YEARS),) $(if $(PACE),--pace $(PACE),) $(if $(VERIFY),--verify,) $(if $(UNIVERSE),--universe-only,)

# Is the archive worth trusting? Internal coherence always; the Coinbase
# cross-check needs `uv sync --extra crypto`.
check-crypto:
	@uv run python -m eulerlab.quality.crypto_check $(if $(NOCROSS),--no-cross,) $(if $(SYMBOLS),--symbols $(SYMBOLS),)

# Install / inspect the launchd job that actually runs `make daily`.
schedule:
	@uv run python tools/schedule_daily.py $(if $(ACTION),$(ACTION),status) $(if $(HOUR),--hour $(HOUR),) $(if $(MINUTE),--minute $(MINUTE),)
