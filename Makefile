.DEFAULT_GOAL := help

.PHONY: full-history nse-reports-intraday option-iv stock-fo minute-six news-intraday tug-of-war option-signals cash-volume cash-events in-play-variants cash-five move-cost-map minute-scalps results-gap-fade expiry-straddle fundamentals-annual screener-models screener data-merge-back agents-watchdog kite-readonly strategy-map board-meetings holidays handbook knowledge-keeper metrics-normals metrics-accept nse-reports market-reports index-minute depth-record depth-day upload-verified help install verify daily daily-run india-live feed coverage test lint fmt types docs-check state acceptance montecarlo tweezer-report india-papers github-daily evidence-daily events-daily tune-sharpe-momentum paper-daily nifty-options options-strategies intraday-papers india-intraday stock-intraday stock-intraday-candidates company-github-intraday github-followup-intraday github-momentum-pullback-intraday inside-bar-intraday github-keltner-intraday github-donchian-intraday github-pivot-intraday github-engulfing-intraday github-momentum-burst-intraday github-rsi2-intraday india-five-intraday nse-earnings-announcements gold-stock-intraday-screen gold-stock-intraday-optimize cost-aware-ml-intraday mcx-gold-minute mcx-gold-backtest angel-mcx-gold-minute library-sync upload-tree fundamentals-update fundamentals-run gap-forecast gap-signal telegram-bot ingest-nse-daily market-history rebuild-ohlc session-studies chaos paper api ui ui-fast web-check results-pull results-dedupe workbench attribution kill-status kill-stop reconcile-book mcx-instruments mcx-index-minute data-quality agent agents agent-brief agents-preopen agents-close agents-weekly agents-ideas agents-work agents-backup agents-restore papers-duplicates agents-capabilities agent-fix-apply relock quantpedia-sync agent-eval fii-dii fii-dii-history microstructure-five microstructure-five-futures microstructure-five-b2 fyers-auth fyers-expired-fo

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
	@echo "  make ui-fast      the same, built once: loads far faster, no live edits"
	@echo "  make workbench    both at once"
	@echo "  make test         pytest only"
	@echo "  make lint         ruff check + format check"
	@echo "  make fmt          apply ruff fixes and formatting"
	@echo "  make install-lite without the news tone model; make remove-news / install-news"
	@echo "  make types        mypy --strict"
	@echo "  make docs-check   fail if src/ changed without docs"
	@echo "  make state        print where the project is"
	@echo ""
	@echo "  make ingest-eod FROM=2015-01-01 [TO=YYYY-MM-DD]"
	@echo "                    download NSE equity + F&O bhavcopy into data/landing/"
	@echo "  make check-landing  re-hash every landed file; proves nothing changed"
	@echo "  make kite-login   obtain a Kite access token (expires 6 AM daily)"
	@echo "  make kite-readonly  check the Kite connection through the adapter; sends nothing"
	@echo "  make fyers-auth   log in to FYERS and save today's access token in .env"
	@echo "  make fyers-expired-fo UNDERLYING=NSE:RELIANCE-EQ FROM=YYYY-MM-DD TO=YYYY-MM-DD"
	@echo "                    fetch approved expired stock-futures 1-minute candles"
	@echo "  make microstructure-five-futures [FROM=...] [EVAL_FROM=...] [TO=...]"
	@echo "                    fetch, normalize, and backtest frozen strategy micro-05"
	@echo "  make microstructure-five-b2  retry B2 upload of the raw and derived micro-05 data"
	@echo "  make nse-reports [FROM=date]  NSE deals, ban list, SLBM, MTF, insider, SAST; to B2"
	@echo "  make index-minute [YEARS=1]   NIFTY 50 / BANK / VIX minute bars; to B2"
	@echo "  make depth-day                record Nifty 50 five-level depth until 15:31; to B2"
	@echo "  make mcx-instruments  fetch today's MCX instrument master and mirror to B2"
	@echo "  make mcx-gold-minute  fetch current Gold futures minutes and mirror to B2"
	@echo "  make mcx-gold-backtest run the frozen MCX Gold rule with costs"
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
	@echo "  make paper-agent TOPIC='...' [LIMIT=5]  find papers, draft cards, stop for approval"
	@echo "  make paper-agent-approve DRAFT=<folder>  move one draft to hypotheses/ and the library"
	@echo "  make quantpedia-sync [LIMIT=50]  land Quantpedia's strategy catalogue (needs a key in .env)"
	@echo "  make data-quality       grade every dataset against the data quality contract"
	@echo "  make fii-dii            capture today's FII/DII cash flows from NSE"
	@echo "  make fii-dii-history    backfill FII/DII history from aggregators (MONTHS=12)"
	@echo "  make agents             list the agents, on or off"
	@echo "  make agent NAME=<agent> [ARGS='k=v ...']  run one agent now"
	@echo "  make agent-brief NAME=<agent|all> TEXT='...'  give an agent standing context"
	@echo "  make agents-preopen / agents-close / agents-weekly  the scheduled agent batches"
	@echo "  make agents-ideas             research, then the idea lab, then engineering; memory to B2 (daily, 17:00 IST)"
	@echo "  make agents-backup            the agents' memory, drafts, papers and trial ledger to B2 (DRY=1 to preview)"
	@echo "  make agents-restore           download that memory back, only into empty folders"
	@echo "  make papers-duplicates        list library papers that look like one paper (changes nothing)"
	@echo "  make agents-work              heads split and check tasks, then due tasks run (ADR-124)"
	@echo "  make agents-capabilities      can every agent do the work it may be given?"
	@echo "  make agent-fix-apply ID=...   merge a fix the engineering agent made and proved"
	@echo "  make knowledge-keeper [MODE=weekly]  refresh metric normals, watch SEBI/RBI/NSE, draft page updates"
	@echo "  make metrics-normals          recompute what is normal for each metric"
	@echo "  make board-meetings           capture today's NSE board-meeting intimations (results calendar)"
	@echo "  make holidays                 fetch this year's NSE trading holidays (the brief skips them)"
	@echo "  make handbook                 rebuild the Market Handbook (workbench /handbook.html)"
	@echo "  make metrics-accept DRAFT=... apply an approved draft page to docs/METRICS"
	@echo "  make agent-eval [ONLY=skeptic|knowledge]  score agents; one that makes up a figure is switched off"
	@echo "  make relock DEPLOYMENT=<id> NOTE='...'  accept a strategy's changed code after review"
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
	@echo "  make india-live   Indian data from 15:31, retried until in (schedulable)"

# Everything this machine runs: the news tone model (ADR-135) and scikit-learn for
# the screener's tree ranker (ADR-136), which holds nothing without it.
install:
	uv sync --extra dev --extra web --extra news --extra research-ml
	cd web && npm install
	uv run pre-commit install

# Without the news tone model (about 1.2 GB): the brief lists headlines unscored.
install-lite:
	uv sync --extra dev --extra web
	cd web && npm install
	uv run pre-commit install

# Add or remove only the news tone model; nothing else changes.
install-news:
	uv sync --inexact --extra news

remove-news:
	uv pip uninstall transformers torch

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

kite-readonly:
	@uv run python -m eulerlab.broker.kite_check

ingest-oi:
	@test -n "$(FROM)" || (echo "usage: make ingest-oi FROM=2020-01-01 [TO=2026-08-18]"; exit 2)
	uv run python -m eulerlab.ingest.backfill_oi --from $(FROM) $(if $(TO),--to $(TO),)

ingest-minute:
	uv run python -m eulerlab.ingest.backfill_minute $(if $(YEARS),--years $(YEARS),) $(if $(LIMIT),--limit $(LIMIT),)

sync-cloud:
	uv run python -m eulerlab.ingest.sync_cloud $(if $(DRY),--dry-run,) $(if $(VERIFY),--verify,)

restore-local:
	uv run python -m eulerlab.ingest.restore_local $(ARGS)

# Mirror data/derived to B2; DROP=path deletes one derived file once B2 holds
# it at the same size and SHA-256.
sync-derived:
	uv run python -m eulerlab.ingest.sync_derived $(if $(DRY),--dry-run,) $(foreach f,$(DROP),--drop $(f))

prune-local:
	uv run python -m eulerlab.ingest.prune_local $(if $(DRY),--dry-run,)

# Upload only the named landing folders: `make upload-tree TREES="nse crypto"`.
# Lists only their part of the bucket. What `make daily` runs after each
# download. DELETE=1 then removes the local files the bucket holds at the same
# size. DRY=1 reports and changes nothing.
# Merge local files that differ from the bucket into it, every row once at its
# earliest knowledge time, then delete them (ADR-132). DRY=1 changes nothing.
data-merge-back:
	@uv run python -m eulerlab.ingest.merge_back $(if $(DRY),--dry-run,) $(if $(LIMIT),--limit $(LIMIT),)

# Every agent's runs, model use and tasks over the last day (ADR-132).
agents-watchdog:
	@uv run python -m eulerlab.agents.runtime watchdog

upload-tree:
	@echo "   upload$(if $(DELETE), then delete local,): $(TREES)"
	@uv run python -m eulerlab.ingest.sync_cloud --only $(TREES) $(if $(DELETE),--then-delete,) $(if $(DRY),--dry-run,)

# Company fundamentals: download, upload to B2, delete the local copies.
# Weekly from launchd (`make schedule ACTION=install JOB=fundamentals`) and
# on demand from here. Takes hours. It holds its own lock, not the feed lock,
# so the nightly job and "Update all data" are not held up by it.
# LIMIT=n fetches only n companies.
fundamentals-update:
	@uv run python -m eulerlab.ingest.filelock fundamentals -- $(MAKE) --no-print-directory fundamentals-run

fundamentals-run:
	@echo "== fundamentals =="
	-uv run python -m eulerlab.fundamentals.backfill $(if $(LIMIT),--limit $(LIMIT),)
	@$(MAKE) --no-print-directory upload-tree TREES="fundamentals" DELETE=1
	-@$(MAKE) --no-print-directory fundamentals-annual

build-master:
	uv run python -m eulerlab.master.build_master $(if $(DAILY),--cadence daily,)

# Current Kite MCX instruments plus their immutable raw response in B2's nse/mcx/ prefix.
mcx-instruments:
	uv run python -m eulerlab.ingest.kite_mcx
	@$(MAKE) --no-print-directory upload-tree TREES="mcx"

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

paper-agent:
	@uv run python -m eulerlab.research.paper_agent --topic "$(TOPIC)" $(if $(LIMIT),--limit $(LIMIT),) $(if $(SOURCES),--sources $(SOURCES),) $(if $(MODEL),--model $(MODEL),)

paper-agent-approve:
	@test -n "$(DRAFT)" || (echo "usage: make paper-agent-approve DRAFT=research/agent_drafts/<run>/<paper>"; exit 2)
	@uv run python -m eulerlab.research.paper_agent --approve "$(DRAFT)"

paper-agent-list:
	@uv run python -m eulerlab.research.paper_agent --list

quantpedia-sync:
	@uv run python -m eulerlab.research.quantpedia $(if $(LIMIT),--limit $(LIMIT),)

# --- the agent network (ADR-085) and the data quality contract (ADR-086) ---
data-quality:
	@uv run python -m eulerlab.quality.contract

agents:
	@uv run python -m eulerlab.agents.runtime

agent:
	@test -n "$(NAME)" || (echo "usage: make agent NAME=<agent> [ARGS='key=value ...']"; exit 2)
	@uv run python -m eulerlab.agents.runtime $(NAME) $(foreach a,$(ARGS),--arg $(a))

agent-brief:
	@test -n "$(NAME)" -a -n "$(TEXT)" || (echo "usage: make agent-brief NAME=<agent|all> TEXT='...'"; exit 2)
	@uv run python -m eulerlab.agents.briefs $(NAME) "$(TEXT)"

agents-preopen:
	-@uv run python -m eulerlab.agents.runtime data
	-@uv run python -m eulerlab.agents.runtime operations
	-@uv run python -m eulerlab.agents.runtime market_brief
	-@uv run python -m eulerlab.agents.runtime head_research
	-@uv run python -m eulerlab.agents.runtime head_platform
	-@uv run python -m eulerlab.agents.runtime head_portfolio
	-@uv run python -m eulerlab.agents.work
	-@uv run python -m eulerlab.agents.runtime watchdog

knowledge-keeper:
	@uv run python -m eulerlab.agents.runtime knowledge_keeper $(if $(MODE),--arg mode=$(MODE),)

board-meetings:
	@uv run python -m eulerlab.ingest.board_meetings

holidays:
	@uv run python -m eulerlab.ingest.holidays

handbook:
	@uv run python tools/render_metrics_handbook.py

metrics-normals:
	@uv run python -m eulerlab.metrics_library.normals

metrics-accept:
	@uv run python -m eulerlab.agents.workers.knowledge_keeper $(DRAFT)

agents-close:
	-@uv run python -m eulerlab.agents.runtime data
	-@uv run python -m eulerlab.agents.runtime operations
	-@uv run python -m eulerlab.agents.runtime portfolio
	-@uv run python -m eulerlab.agents.runtime knowledge_keeper
	-@uv run python tools/render_metrics_handbook.py
	-@uv run python -m eulerlab.agents.runtime engineering --arg mode=quality
	-@uv run python -m eulerlab.agents.runtime watchdog

agents-weekly:
	-@uv run python -m eulerlab.agents.evaluate
	-@uv run python -m eulerlab.research.quantpedia
	-@uv run python -m eulerlab.agents.runtime knowledge_keeper --arg mode=weekly
	-@uv run python -m eulerlab.agents.runtime knowledge
	-@uv run python -m eulerlab.agents.runtime engineering

# Research, then the idea lab, every day (ADR-110). The lab reads the research
# agent's new drafts; research reads the lab's feedback from the day before.
# In order (ADR-128): research finds papers and drafts ideas, the lab backtests
# what it can build, then the work runner hands the rest to engineering and
# runs it, and the day's memory goes to B2.
agents-ideas:
	-@uv run python -m eulerlab.agents.runtime head_research
	-@uv run python -m eulerlab.agents.runtime head_platform
	-@uv run python -m eulerlab.agents.runtime head_portfolio
	-@uv run python -m eulerlab.agents.work
	-@uv run python -m eulerlab.agents.runtime research
	-@uv run python -m eulerlab.agents.runtime lab
	-@uv run python -m eulerlab.agents.work
	-@uv run python -m eulerlab.agents.runtime watchdog
	-@uv run python -m eulerlab.ingest.memory_backup

# The agent company's working day (ADR-124): each head checks finished tasks,
# splits yours (model first, fixed rules if not) and plans its agents' day;
# then the work runner turns hand-offs into tasks and runs the ones that may
# start by themselves. Also inside agents-preopen and agents-ideas.
papers-duplicates:
	@uv run python -m eulerlab.research.paper_agent --duplicates

agents-backup:
	@uv run python -m eulerlab.ingest.memory_backup $(if $(DRY),--dry-run,)

agents-restore:
	@uv run python -m eulerlab.ingest.memory_backup --restore

agents-work:
	-@uv run python -m eulerlab.agents.runtime head_research
	-@uv run python -m eulerlab.agents.runtime head_platform
	-@uv run python -m eulerlab.agents.runtime head_portfolio
	-@uv run python -m eulerlab.agents.work

# Can every agent do the work it may be given? Reads definitions and worker
# source; runs nothing.
agents-capabilities:
	@uv run python -m eulerlab.agents.capabilities

# Merge one engineering-agent fix branch into the checked-out branch (ADR-113).
agent-fix-apply:
	@test -n "$(ID)" || (echo "usage: make agent-fix-apply ID=<fix id from the inbox>"; exit 2)
	@uv run python -m eulerlab.devtools.fixer $(ID)

agent-eval:
	@uv run python -m eulerlab.agents.evaluate $(if $(ONLY),--only $(ONLY),)

relock:
	@test -n "$(DEPLOYMENT)" -a -n "$(NOTE)" || (echo "usage: make relock DEPLOYMENT=<id> NOTE='why the new code is accepted'"; exit 2)
	@uv run python -m eulerlab.deploy.version_lock $(DEPLOYMENT) --note "$(NOTE)"

gate-acceptance:
	@uv run python -m eulerlab.validation.gate_acceptance $(if $(SYMBOLS),--symbols $(SYMBOLS),)

gate:
	@uv run python -m eulerlab.gate_run $(if $(H),--hypothesis $(H),) $(if $(READ_HOLDOUT),--read-holdout $(READ_HOLDOUT),)

validate:
	@uv run python -m eulerlab.validation.run $(if $(H),--hypothesis $(H),)

test-engine:
	@uv run python -m eulerlab.backtest.selftest $(if $(UPDATE),--update-golden,)

backtest:
	@uv run python -m eulerlab.backtest.compare $(if $(ALLOW_LOW),--allow-low-grade,) $(if $(STRAT),--strategy $(STRAT),) $(if $(FEATURE),--feature $(FEATURE),) $(if $(REBALANCE),--rebalance $(REBALANCE),) $(if $(MIN_TURNOVER),--min-turnover $(MIN_TURNOVER),)

backtest-fast:
	@uv run python -m eulerlab.backtest.report $(if $(ALLOW_LOW),--allow-low-grade,) $(if $(STRAT),--strategy $(STRAT),) $(if $(FEATURE),--feature $(FEATURE),) $(if $(REBALANCE),--rebalance $(REBALANCE),) $(if $(MIN_TURNOVER),--min-turnover $(MIN_TURNOVER),) $(if $(COMPARE),--compare,)

ic:
	@uv run python -m eulerlab.features.tearsheet $(if $(FEATURE),--feature $(FEATURE),) $(if $(HORIZON),--horizon $(HORIZON),) $(if $(ALL),--all,)

build-panel:
	@uv run python -m eulerlab.features.build_panel $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),)

build-factors:
	uv run python -m eulerlab.corp_actions.build_factors $(if $(LIMIT_FILES),--limit-files $(LIMIT_FILES),)

# One command to keep every dataset current, safe to schedule. Each step is
# idempotent: already-current data costs nothing, so re-running is cheap and
# a missed day self-heals on the next run.
# --reload-dir src: without it uvicorn polls every file under the repo,
# data/ included (64,323 files), four times a second for changed .py files:
# a whole CPU core, all day (measured 2026-10-27). src/ is 618 files.
api:
	uv run --extra web uvicorn eulerlab.api.server:app --host 127.0.0.1 --port 8000 --reload --reload-dir src

ui:
	-@uv run python tools/render_metrics_handbook.py
	cd web && npm install --silent && npm run dev

# Download and merge every backtest result from the bucket, whatever its size.
# The mirror after a batch skips files whose size matches; this does not.
results-pull:
	uv run python -m eulerlab.cloud_results

# Drop result rows that repeat another row in everything but the time written,
# here and in the bucket. Shows what it would do; APPLY=1 does it.
results-dedupe:
	@uv run python -m eulerlab.cloud_results --dedupe $(if $(APPLY),--apply,)

# The web code's own gates: types and the Next lint rules.
web-check:
	cd web && npm run typecheck && npm run lint && npm test

# The UI built once and served as built: what to run when using the app, not
# changing it. `make ui` compiles each screen on first visit and ships a
# development bundle several times the size.
ui-fast:
	cd web && npm install --silent && npm run build && npm run start

workbench:
	@echo "starting the API on :8000 and the UI on :3000"
	@$(MAKE) -j2 api ui

acceptance:
	@uv run python tools/acceptance.py $(if $(ALL),--all,)

tweezer:
	@uv run python -m eulerlab.intraday.scan $(if $(UNIVERSE),--universe $(UNIVERSE),$(if $(SYMBOLS),,--universe nifty50)) $(if $(SYMBOLS),--symbols $(SYMBOLS),) $(if $(DAY),--day $(DAY),) $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),) $(if $(WORKERS),--workers $(WORKERS),) $(if $(QUIET),--quiet,) $(if $(PRUNE),--prune,)

# FII/DII provisional cash flows. NSE serves the latest day only, so this is
# capture-only: run it every trading evening (`make daily` does). ADR-098.
# REBUILD=1 rewrites data/derived/fii_dii_cash.jsonl from the landed files.
fii-dii:
	@uv run python -m eulerlab.ingest.fii_dii_cash $(if $(REBUILD),--rebuild,)

# Backfill FII/DII days NSE no longer serves, from Trendlyne, cross-checked
# against Groww and stockezee (ADR-099). One page per month, 2.5 s apart.
MONTHS ?= 12
fii-dii-history:
	@uv run python -m eulerlab.ingest.fii_dii_history --months $(MONTHS)

ingest-nse-daily:
	@test -n "$(FROM)" || (echo "usage: make ingest-nse-daily FROM=2015-01-01 [TO=...]"; exit 2)
	uv run python -m eulerlab.ingest.nse_daily_files --from $(FROM) $(if $(TO),--to $(TO),)

market-history:
	uv run python -m eulerlab.market_history $(if $(SKIP_EXPIRIES),--skip-expiries,) $(if $(FULL),--full,)

session-studies:
	uv run python -m eulerlab.research.session_studies

# Research 072: Mukherjee & Mandal (2025) as written, then traded on the future.
gap-forecast:
	@uv run python -m eulerlab.research.gap_forecast_run

# Tonight's decision for the registered gap strategy, sent to Telegram. Run
# between 15:15 and 15:25 IST; needs a Kite token minted today. DRY=1 prints only.
gap-signal:
	@uv run python -m eulerlab.research.gap_signal $(if $(DRY),--dry-run,) $(if $(SCHEDULED),--scheduled,)

# Answer the operator's Telegram messages (status, positions, orders, next,
# signal, data, strategies, help). Read-only. The API runs this itself; use
# this target when the workbench is not running.
telegram-bot:
	@uv run python -m eulerlab.telegram_bot

rebuild-ohlc:
	uv run python -m eulerlab.features.rebuild_ohlc $(if $(SWAP),--swap,)

# ADR-106: how alike are the stored daily strategies? Reads stored reports only; spends no trial.
strategy-map:
	@uv run python -m eulerlab.research.strategy_map

india-papers:
	@uv run --extra web python -m eulerlab.research.run_india $(if $(ONLY),--only $(ONLY),)

# The stock screener (ADR-136): point-in-time annual fundamentals, the six models'
# backtests (screening runs, no trial spent), and today's lists.
fundamentals-annual:
	@uv run python -m eulerlab.screener build-fundamentals

screener-models:
	@uv run --extra web python -m eulerlab.research.run_india --set screener $(if $(ONLY),--only $(ONLY),)

screener:
	@uv run python -m eulerlab.screener build

# Research 113: five daily rules from GitHub repositories, on the same engine and window.
github-daily:
	@uv run --extra web python -m eulerlab.research.run_india --set github $(if $(ONLY),--only $(ONLY),)

# Research 113 batch 3: momentum and reversal refinements with published evidence.
evidence-daily:
	@uv run --extra web python -m eulerlab.research.run_india --set evidence $(if $(ONLY),--only $(ONLY),)

# Research 113 batch 5: earnings-event strategies, on the announcement data's window.
events-daily:
	@uv run --extra web python -m eulerlab.research.run_india --set events $(if $(ONLY),--only $(ONLY),)

# Sweep volatility-adjusted momentum's window, names held and rebalance; choose
# on 2016-2023, test once on 2024 on. Resumable. Research 067.
tune-sharpe-momentum:
	@uv run python -m eulerlab.research.tune_sharpe_momentum $(if $(ANALYSE),--analyse-only,)

tweezer-report:
	@uv run python -m eulerlab.intraday.tweezer_report $(if $(HOLD),--hold $(HOLD),--hold 1,5,20) $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),)

montecarlo:
	@uv run python -m eulerlab.validation.montecarlo_run $(if $(FEATURE),--feature $(FEATURE),) $(if $(DAYS),--days $(DAYS),) $(if $(SIMS),--simulations $(SIMS),)

chaos:
	@uv run python -m eulerlab.oms.chaos

kill-status:
	@uv run python -m eulerlab.oms.killswitch

kill-stop:
	@test -n "$(REASON)" || (echo 'usage: make kill-stop REASON="why"'; exit 2)
	@uv run python -m eulerlab.oms.killswitch --trip "$(REASON)"

# Every Nifty option and future from the daily F&O bhavcopy, one line per day.
# Resumable. Research 070.
nifty-options:
	@uv run python -m eulerlab.options.nifty_history $(if $(FROM),--from $(FROM),)

# Research 070's two strategies on the Nifty options history.
options-strategies:
	@uv run python -m eulerlab.options.run_strategies

# Research 071's two intraday papers on NIFTYBEES minute bars.
intraday-papers:
	@uv run python -m eulerlab.intraday.session_papers_run $(if $(SYMBOL),--symbol $(SYMBOL),)

# Research 076: five intraday rules from Indian sources. NIFTYBEES for the
# three index rules, the 100 largest stocks for the other two. About 15 minutes;
# INDEX_ONLY=1 runs the index rules alone in seconds.
india-intraday:
	@uv run python -m eulerlab.intraday.india_papers_run $(if $(INDEX_ONLY),--index-only,) $(if $(STOCKS),--stocks $(STOCKS),)

# Research 078: two stock rules from US papers (end-of-day reversal, the
# opening half-hour repeating) on the 100 largest stocks. About 4 minutes.
stock-intraday:
	@uv run python -m eulerlab.intraday.stock_papers_run $(if $(STOCKS),--stocks $(STOCKS),)

# Research 087: price-only tests of three non-duplicate Indian stock ideas.
stock-intraday-candidates:
	@uv run python -m eulerlab.intraday.stock_candidate_screen

# Research 088: public company/GitHub candidates screened on the fixed NSE
# minute universe. Volume-profile results are HLC3-weighted OHLCV proxies.
company-github-intraday:
	@uv run python -m eulerlab.intraday.company_github_screen

# Research 089: additional GitHub strategy screen; one new price-data rule.
github-followup-intraday:
	@uv run python -m eulerlab.intraday.github_followup_screen

# Research 090: GitHub surge/pullback continuation, using frozen code defaults.
github-momentum-pullback-intraday:
	@uv run python -m eulerlab.intraday.github_momentum_pullback_screen

# Research 093: 5-minute inside-bar breakout on fixed NSE stocks.
inside-bar-intraday:
	@uv run python -m eulerlab.intraday.inside_bar_screen

# Research 094: source-defined Hikkake false-breakout pattern on NSE minutes.
hikkake-intraday:
	@uv run python -m eulerlab.intraday.hikkake_screen

# Research 095: price-only 5/15 EMA crossover adaptation from a GitHub repo.
github-ema-crossover-intraday:
	@uv run python -m eulerlab.intraday.github_ema_crossover_screen

# Research 096: hourly trend-aligned 15-minute Supertrend re-entry.
supertrend-alignment-intraday:
	@uv run python -m eulerlab.intraday.supertrend_alignment_screen

# Research 097: lagged NSE participant-wise FII index-futures positioning.
fii-positioning-intraday:
	@uv run python -m eulerlab.intraday.fii_participant_oi_screen

# Research 103: cost-aware 30-minute Random Forest signal adapted to NSE stocks.
cost-aware-ml-intraday:
	@uv run --extra research-ml python -m eulerlab.intraday.cost_aware_ml_screen

# Research 106: simple GitHub Keltner Channel close breakout.
github-keltner-intraday:
	@uv run python -m eulerlab.intraday.github_keltner_screen

# Research 107: simple GitHub Turtle/Donchian 5-minute channel breakout.
github-donchian-intraday:
	@uv run python -m eulerlab.intraday.github_donchian_screen

# Research 108: simple GitHub prior-day pivot breakout.
github-pivot-intraday:
	@uv run python -m eulerlab.intraday.github_pivot_breakout_screen

# Research 109: GitHub engulfing + volume + RSI screen, adapted to NSE.
github-engulfing-intraday:
	@uv run python -m eulerlab.intraday.github_engulfing_screen

# Research 110: GitHub 3-bar ATR momentum burst with volume confirmation.
github-momentum-burst-intraday:
	@uv run python -m eulerlab.intraday.github_momentum_burst_screen

# Research 111: GitHub Connors RSI(2) pullback with SMA trend and exit.
github-rsi2-intraday:
	@uv run python -m eulerlab.intraday.github_rsi2_pullback_screen

# Research 112: five Indian intraday rules over every F&O stock, one pass (~15 min).
india-five-intraday:
	@uv run python -m eulerlab.intraday.india_five_screen

# Research 153 (H-0040): fade the results-morning gap, from the india-five cache.
results-gap-fade:
	@uv run python -m eulerlab.intraday.results_gap_fade_screen

# Research 153 (H-0041): sell the Nifty straddle at the open on expiry day.
expiry-straddle:
	@uv run python -m eulerlab.options.expiry_straddle_screen

# Research 166: four Nifty/BankNifty futures rules on 15-minute bars, and four
# index-option expiry-day straddles (H-0041, H-0103 to H-0105). No trial spent.
index-futures:
	@uv run python -m eulerlab.intraday.index_futures_screen

index-expiry:
	@uv run python -m eulerlab.options.index_expiry_screen

# Stored reports for research 166-173's gated stock strategies, so the library shows them (no trial).
library-reports:
	@uv run python -m eulerlab.research.library_reports $(if $(H),--only $(H),)

# Research 174: which stocks were trade-for-trade each day, from the cash bhavcopies.
trade-for-trade:
	@uv run python -m eulerlab.ingest.trade_for_trade

# Research 173: research 172's PROMOTEs on every liquid NSE stock, daily bars (H-0161, H-0162).
daily-universe:
	@uv run python -m eulerlab.intraday.daily_universe_screen

# Research 172: five swing and five intraday rules on non-price data (H-0151 to H-0160).
other-data-screen:
	@uv run python -m eulerlab.intraday.other_data_screen

# Research 171: ten stock day trades at 1x (H-0141 to H-0150).
onex-screen:
	@uv run python -m eulerlab.intraday.onex_screen

# Research 170: ten paper-backed, market-neutral stock day trades (H-0131 to H-0140).
quant-screen:
	@uv run python -m eulerlab.intraday.quant_screen

# Research 168: ten MFT-style stock scalps on 5-minute closes at Zerodha MIS size (H-0111 to H-0120).
mft-screen:
	@uv run python -m eulerlab.intraday.mft_screen

# Research 167: four stock fades after NSE clarification queries (H-0107 to H-0110).
nse-queries:
	@uv run python -m eulerlab.intraday.nse_query_screen

# Research 154: how far stocks move in minutes, against a round trip's cost.
move-cost-map:
	@uv run python -m eulerlab.intraday.move_cost_map

# Research 154 (H-0042, H-0043): two minute-level scalps on F&O stocks.
minute-scalps:
	@uv run python -m eulerlab.intraday.minute_scalp_screen

# Research 155 (H-0045 to H-0049): five minute-level cash rules at 1x.
cash-five:
	@uv run python -m eulerlab.intraday.cash_five_screen

# Research 155 (H-0050): the in-play ORB with fewer trades, chosen on 2021-2023, tested on 2024.
in-play-variants:
	@uv run python -m eulerlab.intraday.in_play_variants

# Research 156 (H-0051 to H-0055): drift bursts and calendar days, cash, 1x.
cash-events:
	@uv run python -m eulerlab.intraday.cash_events_screen

# Research 157 (H-0056 to H-0060): intraday persistence, volume and attention, cash, 1x.
cash-volume:
	@uv run python -m eulerlab.intraday.cash_volume_screen

# Research 158 (H-0061 to H-0065): option-signal, half-hour and overnight-winner cash rules, 1x.
option-signals:
	@uv run python -m eulerlab.intraday.option_signal_screen

# Research 159 (H-0066 to H-0070): overnight-daytime tug-of-war cash rules, 1x.
tug-of-war:
	@uv run python -m eulerlab.intraday.tug_of_war_screen $(if $(DAILY),--daily,)

# Research 160 (H-0072 to H-0076): intraday news rules from NSE corporate announcements.
news-intraday:
	@uv run python -m eulerlab.intraday.news_screen

# Research 161 (H-0077 to H-0082): laggards, intraday pairs, ex-dates, VWAP stretch, 1x.
minute-six:
	@uv run python -m eulerlab.intraday.minute_six_screen

# Research 162 (H-0083 to H-0087): beta, MAX, illiquid last half-hour, pinning, OI build-up. Needs `make minute-six` first.
stock-fo:
	@uv run python -m eulerlab.intraday.stock_fo_screen

# Research 163 (H-0088 to H-0092): skew, call-put IV, IV changes, put-call volume, RV minus IV. Needs `make minute-six` first.
option-iv:
	@uv run python -m eulerlab.intraday.option_iv_screen

# Research 164 (H-0093 to H-0097): bulk deals, SAST promoter buying, F&O ban entry, SLBM borrowing. Needs `make minute-six` and the reports backfilled from 2021-07-01.
nse-reports-intraday:
	@uv run python -m eulerlab.intraday.nse_reports_screen

# ADR-143: the gate's PROMOTE and PAPER strategies from 2016 to the holdout end. READS THE HOLDOUT.
full-history:
	@test -n "$(READ_HOLDOUT)" || (echo "usage: make full-history READ_HOLDOUT=<operator>  (records a holdout read per strategy)"; exit 2)
	@uv run python -m eulerlab.research.full_history --read-holdout "$(READ_HOLDOUT)"

# Five paper-driven microstructure rules: inspect the required data and save a
# readiness report before spending any strategy trials.
microstructure-five:
	@uv run python -m eulerlab.intraday.microstructure_five --output docs/RESEARCH/133-microstructure-five-readiness.json

# FYERS' official individual-app login and approved expired-F&O history path.
fyers-auth:
	@uv run python -m eulerlab.ingest.fyers_expired_fo auth

fyers-expired-fo:
	@uv run python -m eulerlab.ingest.fyers_expired_fo fetch --underlying "$(UNDERLYING)" --from "$(FROM)" --to "$(TO)"

# One fixed single-stock-future lead/cash evaluation; no parameter search.
microstructure-five-futures:
	@uv run python -m eulerlab.intraday.futures_cash_backtest --underlying "$(or $(UNDERLYING),NSE:RELIANCE-EQ)" --cash-symbol "$(or $(CASH_SYMBOL),RELIANCE)" --from "$(or $(FROM),2026-03-01)" --evaluation-from "$(or $(EVAL_FROM),2026-06-01)" --to "$(or $(TO),2026-08-03)"

# Retry both mirrors without another FYERS login or market-data request.
microstructure-five-b2:
	@uv run python -m eulerlab.ingest.sync_cloud --only fyers_expired_fo --verify
	@uv run python -m eulerlab.ingest.sync_derived --root data/derived/microstructure_five/micro-05 --verify

# NSE results-filing timestamps: lands each finished quarter once, then derives.
nse-earnings-announcements:
	@uv run python -m eulerlab.ingest.nse_earnings_announcements

# Research 084: fixed Gold ETF moving-average and Indian stock reversal screens.
gold-stock-intraday-screen:
	@uv run --extra research-ml python -m eulerlab.intraday.research_screen

gold-stock-intraday-optimize:
	@uv run --extra research-ml python -m eulerlab.intraday.strategy_optimizer

# Copy each research study's stored results into the strategy library. Safe
# to run again; run it after any of the four study targets.
library-sync:
	@uv run python -m eulerlab.research.library_sync

# Every active paper deployment, replayed to the latest close: catches up
# missed days, sends nothing twice, halts on a broken book. ADR-060.
# What the Instruments "Update all data" button runs, from a terminal: fetch
# only what is missing, rebuild every table and the paper books, mirror what
# the cloud lacks. Refused while `make daily` holds the feed lock.
feed:
	@uv run python -m eulerlab.ingest.daily_feed

coverage:
	@uv run python -m eulerlab.ingest.coverage

paper-daily:
	@uv run python -m eulerlab.deploy.runner $(if $(ONLY),--only $(ONLY),)

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
	@uv run python -c "from eulerlab.broker.kite_session import check_fresh; raise SystemExit(check_fresh())"

# Minute bars for the last few sessions. NOT a backfill: --years 5 is a one-off
# of ~13,500 chunks, this keeps the tail current.
daily-minute:
	@$(MAKE) --no-print-directory kite-fresh && 	  uv run python -m eulerlab.ingest.backfill_minute --years 1 $(if $(LIMIT),--limit $(LIMIT),)

# Five-year MCX iCOMDEX minute history; the manifest makes repeats incremental.
# NSE daily reports: bulk/block deals, short selling, F&O ban, SLBM, MTF,
# insider (PIT) and SAST filings, plus today's pledge, IPO and Nifty 50 list
# snapshots. Research 130, ADR-095. FROM defaults to a week back.
nse-reports:
	-uv run python -m eulerlab.ingest.nse_reports --from $(if $(FROM),$(FROM),$$(date -v-7d +%Y-%m-%d))
	-@$(MAKE) --no-print-directory market-reports
	@$(MAKE) --no-print-directory upload-verified TREES="nse_reports"

# Dashboard → India → Deals & filings, from the landed reports (ADR-096).
# Runs inside nse-reports, before the upload deletes the local copies.
market-reports:
	uv run python -m eulerlab.market_reports

# Kite 1-minute candles for NIFTY 50, NIFTY BANK and INDIA VIX. YEARS=1 default.
index-minute:
	@$(MAKE) --no-print-directory kite-fresh && uv run python -m eulerlab.ingest.kite_index_minute $(if $(YEARS),--years $(YEARS),)
	@$(MAKE) --no-print-directory upload-verified TREES="kite_index_minute"

# Kite five-level depth for the Nifty 50, the index and the near future, until
# 15:31 IST. depth-day records, then uploads and deletes after verification.
depth-record:
	@$(MAKE) --no-print-directory kite-fresh && uv run python -m eulerlab.ingest.depth_recorder $(if $(RUN_SECONDS),--seconds $(RUN_SECONDS),)

depth-day:
	-@$(MAKE) --no-print-directory depth-record
	@$(MAKE) --no-print-directory upload-verified TREES="kite_depth"

# Upload trees to B2 and delete a local file only when the bucket's size and
# SHA-256 match it. KEEP=1 verifies without deleting.
upload-verified:
	@uv run python -m eulerlab.ingest.verified_prune $(TREES) $(if $(KEEP),--keep,)

mcx-index-minute:
	@$(MAKE) --no-print-directory kite-fresh && uv run python -m eulerlab.ingest.kite_mcx_indices --years 5

# Available minute history for the current standard MCX Gold contract only.
# Kite's continuous API returns expired-futures candles at daily frequency.
mcx-gold-minute:
	@$(MAKE) --no-print-directory kite-fresh && uv run python -m eulerlab.ingest.kite_mcx_gold --years 5
	@$(MAKE) --no-print-directory upload-tree TREES="mcx_gold"

mcx-gold-backtest:
	@uv run python -m eulerlab.intraday.mcx_gold_backtest

# Angel One's active MCX Gold token supplies the rolled front-month minute series.
angel-mcx-gold-minute:
	@uv run --extra angel -m eulerlab.ingest.angel_mcx_gold $(if $(YEARS),--years $(YEARS),)
	@$(MAKE) --no-print-directory upload-tree TREES="angel_mcx_gold"

# The Indian data from 15:31 IST, retried every 10 minutes until the bhavcopy
# and minute bars are in (or 21:00); minute bars stand in meanwhile. ADR-079.
# Scheduled by `make schedule ACTION=install JOB=india-live`. ONCE=1: one pass.
india-live:
	@uv run python -m eulerlab.ingest.india_live $(if $(ONCE),--once,)

# `daily` holds the `feed` lock for the whole run, the lock the Instruments
# button takes too, so the overnight job and a click cannot both append the
# same day (T-4032). If the other holds it, this exits 75 and says who.
daily:
	@uv run python -m eulerlab.ingest.filelock feed -- $(MAKE) --no-print-directory daily-run

daily-run:
	@# One dataset at a time: download it, upload its folder to B2, delete the
	@# local copy, then the next (`upload-tree ... DELETE=1`). A file is deleted
	@# only when a fresh listing shows it in the bucket at the same size, so a
	@# failed upload keeps its file. Two folders are deleted a little later
	@# than they are uploaded, because a build right after reads them: the NSE
	@# files (market history, price panel, Nifty options, paper books) and the
	@# US files (US panel). Until 2026-10-13 everything was downloaded first
	@# and uploaded once at the end, behind fundamentals.
	@echo "== EOD bhavcopy =="
	-uv run python -m eulerlab.ingest.nse_eod --from $$(date -v-7d +%Y-%m-%d)
	-@$(MAKE) --no-print-directory upload-tree TREES="nse"
	@echo "== participant OI =="
	-uv run python -m eulerlab.ingest.backfill_oi --from $$(date -v-7d +%Y-%m-%d)
	@echo "== NSE reports (deals, ban list, SLBM, MTF, insider, SAST, snapshots) =="
	-$(MAKE) --no-print-directory nse-reports
	@echo "== NSE index closes (incl. India VIX) and delivery =="
	-uv run python -m eulerlab.ingest.nse_daily_files --from $$(date -v-7d +%Y-%m-%d)
	-@$(MAKE) --no-print-directory upload-tree TREES="nse"
	@echo "== FII/DII cash flows (NSE serves today only) =="
	-uv run python -m eulerlab.ingest.fii_dii_cash
	-@$(MAKE) --no-print-directory upload-tree TREES="fii_dii" DELETE=1
	-uv run python -m eulerlab.market_history --skip-expiries
	@# The panel and the paper books come straight after the bhavcopy, from the
	@# local landed file, so a slow or failed network step below cannot leave
	@# them a day behind (2026-10-08, RUNBOOKS/paper-books-behind.md).
	@echo "== price panel =="
	-$(MAKE) --no-print-directory build-panel
	@echo "== Nifty options (last 30 days, only days not stored) =="
	-$(MAKE) --no-print-directory nifty-options FROM=$$(date -v-30d +%Y-%m-%d)
	@echo "== paper deployments (bring each up to the latest close) =="
	-$(MAKE) --no-print-directory paper-daily
	@# The builds above have read today's NSE files; the local copies can go.
	-@$(MAKE) --no-print-directory upload-tree TREES="nse" DELETE=1
	@echo "== mutual fund NAVs =="
	-uv run python -m eulerlab.ingest.mf_backfill --snapshot-only
	-@$(MAKE) --no-print-directory upload-tree TREES="mf" DELETE=1
	@echo "== economic calendar =="
	-uv run python -m eulerlab.ingest.forexfactory
	-@$(MAKE) --no-print-directory upload-tree TREES="calendar" DELETE=1
	@echo "== NSE holidays, then the after-close note (now the day's closes, flows and calendar are in) =="
	-uv run python -m eulerlab.ingest.holidays
	-uv run python -m eulerlab.ingest.board_meetings
	-uv run python -m eulerlab.agents.runtime market_brief --arg mode=after-close
	@echo "== minute bars (needs a token minted today) =="
	-$(MAKE) --no-print-directory daily-minute
	@echo "== provisional daily bars (minute bars while the bhavcopy is missing) =="
	-uv run python -m eulerlab.ingest.provisional_daily
	-@$(MAKE) --no-print-directory upload-tree TREES="kite_minute" DELETE=1
	@echo "== index minute bars: NIFTY 50, NIFTY BANK, INDIA VIX (needs a token minted today) =="
	-$(MAKE) --no-print-directory index-minute
	@echo "== MCX iCOMDEX minute bars (needs a token minted today) =="
	-$(MAKE) --no-print-directory mcx-index-minute
	-@$(MAKE) --no-print-directory upload-tree TREES="mcx_indices" DELETE=1
	@echo "== crypto (Binance public archive, no auth) =="
	-uv run python -m eulerlab.ingest.crypto_backfill --years 1
	@echo "== crypto month-end gap (Binance daily archive) =="
	-uv run python -m eulerlab.ingest.crypto_fill
	-@$(MAKE) --no-print-directory upload-tree TREES="crypto" DELETE=1
	@echo "== FX (FXCM weekly candles) =="
	-uv run python -m eulerlab.ingest.fx_bulk_backfill --from-year $$(date +%Y)
	-@$(MAKE) --no-print-directory upload-tree TREES="fx" DELETE=1
	@echo "== market-wide news and its tone (uploaded with the news below) =="
	-uv run python -m eulerlab.ingest.market_news
	@echo "== per-instrument news (equity, crypto, FX) =="
	-uv run python -m eulerlab.ingest.news
	-@$(MAKE) --no-print-directory upload-tree TREES="news names" DELETE=1
	@echo "== index levels, movers, sectors =="
	-uv run python -m eulerlab.indices
	-@$(MAKE) --no-print-directory upload-tree TREES="marketdata" DELETE=1
	@echo "== US bars, actions, news =="
	@# From the first of last month, not 2016. Re-fetching ten years every
	@# night rewrote ~37,000 files and the upload after it ran for hours and
	@# never finished (HISTORY #68). The history is in B2; `make us-bars
	@# FROM=2016-01-01` refills it on demand.
	-uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); alpaca.land_bars([*s, 'SPY'], start='$$(date -v-1m +%Y-%m-01)'); alpaca.land_actions(s, start='$$(date -v-1m +%Y-%m-01)'); alpaca.land_news(s, start='2026-06-01')"
	-@$(MAKE) --no-print-directory upload-tree TREES="us"
	@echo "== US panel =="
	-$(MAKE) --no-print-directory build-us-panel
	-@$(MAKE) --no-print-directory upload-tree TREES="us" DELETE=1
	@# Fundamentals is not here any more: it walks every symbol and took over
	@# ten hours on 2026-10-08. It runs weekly and on demand
	@# (`make fundamentals-update`).
	@# A last sweep of every folder: it sends and removes whatever a step above
	@# could not, and anything no step names.
	@echo "== stock screener: today's lists and the selection history (ADR-136) =="
	-$(MAKE) --no-print-directory screener
	@echo "== sync and prune =="
	-$(MAKE) sync-cloud
	$(MAKE) prune-local
	@# Files that differ from the bucket are merged into it, rows once, and
	@# deleted (ADR-132). Not ignored: one it cannot merge fails the run, so
	@# daily_guard.sh sends the failure to Telegram.
	@echo "== merge what differs from B2 =="
	$(MAKE) --no-print-directory data-merge-back
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

# Market-wide and geopolitical news for the brief, with its tone (ADR-134).
market-news:
	@uv run python -m eulerlab.ingest.market_news

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
	@uv run python -c "from eulerlab.ingest import alpaca; s=alpaca.sp500_symbols(); w,n,e=alpaca.land_bars([*s, 'SPY'], start='$(FROM)' or '2016-01-01'); print(f'{w} symbols, {n:,} bars {e}')"

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
# Sweep every strategy on the market its paper tested. NOT in `daily`: every
# configuration evaluated is permanent and raises the deflated-Sharpe bar for
# every result this platform will ever produce, so it runs when an operator
# asks for it and never on a timer.
#
#   make optimize DRY=1        evaluate without spending trials
#   make optimize ONLY=orb_breakout
optimize:
	@uv run python -m eulerlab.optimize_run $(if $(DRY),--dry-run,) $(if $(ONLY),--only $(ONLY),) $(if $(FROM),--start $(FROM),) $(if $(TO),--end $(TO),)

# Run every swept strategy once on the parameters it actually uses, and cache
# the result the library shows. Spends no trials: it re-runs only settings a
# recorded sweep already contains.
adopted-results:
	@uv run python -m eulerlab.adopted_run $(if $(ONLY),--only $(ONLY),)

# Run every strategy on US equity, whatever market its paper used. Asks whether
# a signal works on QQQ at all, which for the ten crypto signals is a question
# nothing here has answered. Spends one trial per strategy: a signal on a new
# instrument is a new configuration.
us-all:
	@uv run python -m eulerlab.us_all_run $(if $(ONLY),--only $(ONLY),)

# Walk-forward a strategy's sweep and estimate its probability of backtest
# overfitting. Spends no trials: candidates are evaluated once and the sessions
# re-partitioned. `make walk STRATEGY=ou_reversion_in`
walk:
	@uv run python -m eulerlab.walk_run $(STRATEGY)

# Keep one stored run per strategy — the adopted one — and drop superseded
# payloads. The *count* each keeper stands in for is preserved, so the
# selection-bias denominator is unchanged. Dry by default; --apply to write.
prune-runs:
	@uv run python -m eulerlab.prune_runs $(if $(APPLY),--apply,)

# Where every result and trial lives, and which of them the noise bar is
# charged for. Read-only.
evidence:
	@uv run python -m eulerlab.evidence

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
	@uv run python tools/schedule_daily.py $(if $(ACTION),$(ACTION),status) $(if $(JOB),--job $(JOB),) $(if $(HOUR),--hour $(HOUR),) $(if $(MINUTE),--minute $(MINUTE),)

# The project's own auditor: defect shapes this codebase actually produces,
# a smoke run of every registered strategy, and the strategy-to-file map.
# REVIEW=1 adds an advisory model pass over the working diff.
audit:
	@uv run python -m eulerlab.audit $(if $(REVIEW),--review,) $(if $(PROVIDER),--provider $(PROVIDER),)

audit-strategies:
	@uv run python -m eulerlab.audit --inventory
