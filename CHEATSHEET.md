# EulerLab — Quick Reference

Plain-English notes on the commands you actually run and the files you actually
look at. The full list of targets is `make help`. Rules of the house:
`CLAUDE.md`; where the project stands: `STATE.md`.

---

## 1. Starting and stopping the web app (the servers)

| What you want | Command | Details |
|---|---|---|
| API + UI together | `make workbench` | API on `:8000`, UI on `:3000` |
| API only | `make api` | uvicorn on `:8000`, auto-reloads on code change |
| UI only, fast | `make ui-fast` | built once, loads quickly — for using the app |
| UI only, dev | `make ui` | live-editing mode, slower |
| See what is running | `ps aux \| grep -i eulerlab` | shows you every project process |
| Stop a server | `kill -TERM <pid>` | restart anything in `make workbench` afterwards |
| Server logs | `data/logs/api.log`, `data/logs/ui.log` | check here when a screen is blank or slow |

A server stays running after you close the terminal that started it. If one
`make workbench` stalls, stop the API and the UI with `kill`, then run it again.
The API holding ~100% CPU is a sign it needs a restart.

---

## 2. Data fetching (downloads)

### The one daily job: `make daily`

`make daily` is the "refresh everything" job. It holds a **feed lock** so two
runs can never append the same day twice. Inside it (`daily-run`) it runs, in
order:

EOD bhavcopy → participant open interest → index closes + India VIX →
price panel → Nifty options → replay paper books → MF NAVs → economic
calendar → minute bars → fundamentals.

Every step is already covered by the download; it re-runs safely.

### Why you saw *"Another data run is going… Wait for it to finish."*

That message comes from the feed lock. `make daily` was already running, so
your fetch was refused rather than allowed to collide with it. It is not an
error — it is the system protecting the data from double-appending. The message
names the process and when it started; when that process ends, the lock frees
and you can run your fetch again.

### Fetching individual datasets

| Command | What it downloads |
|---|---|
| `make ingest-eod FROM=2015-01-01` | NSE daily bhavcopy (prices) |
| `make ingest-oi FROM=2020-01-01` | NSE participant-wise F&O open interest |
| `make ingest-minute YEARS=5` | 1-minute candles for the universe |
| `make ingest-fundamentals` | screener.in fundamentals (slow; skips names done today) |
| `make ingest-corp-actions FROM_YEAR=2015` | dividends, bonuses, splits, rights |
| `make kite-login` | new Kite access token (expires 6 AM daily) |
| `make sync-cloud` | mirror landed data to Backblaze B2 (off-site backup) |
| `make feed` | the same job the UI's "Update all data" button runs |

All downloads land in `data/landing/` and are never edited or deleted after.
Raw files are immutable.

### Checking things are still right

| Command | What it proves |
|---|---|
| `make check-landing` | re-hashes every downloaded file — nothing was altered |
| `make provenance` | shows which data is point-in-time and which is not |
| `make check-master` | security master acceptance checks |
| `make reconcile` | bhavcopy vs Kite prices, two vendors agreeing |
| `make quality` | data quality report |

### Stopping a fetch

Find the process tree and kill it from the top:

```bash
ps -eo pid,ppid,command | grep -iE "make daily|daily-run|backfill|filelock"
kill -TERM <top-most-pid>
```

Killing it releases the feed lock automatically. Data already written stays;
re-running later just picks up where it left off.

---

## 3. The checks that keep the system honest

| Command | What it runs |
|---|---|
| `make verify` | the one command: every gate, ~1000 tests, summary table |
| `make test` | pytest only |
| `make lint` | ruff style + format |
| `make types` | mypy --strict |
| `make fmt` | auto-fix formatting |
| `make state` | print where the project stands |

Run `make verify` after any change; if it is not green, the change is not done.

---

## 4. Strategy research vocabulary

| Command | Meaning |
|---|---|
| `make research` | the research loop: idea cards → critic → gate verdicts |
| `make gate H=H-0001` | apply the mandate: PROMOTE or KILL |
| `make validate H=H-0001` | overfitting battery (CPCV, DSR, PBO, MinBTL) |
| `make backtest STRAT=rank FEATURE=momentum_12_1` | Tier B event-driven backtest |
| `make backtest-fast STRAT=rank FEATURE=momentum_12_1` | Tier A vectorised backtest |
| `make ic FEATURE=momentum_12_1` | information coefficient tear sheet |
| `make montecarlo FEATURE=...` | drawdown risk + Sharpe confidence interval |
| `make paper FEATURE=...` | run a strategy through the OMS against a paper broker |
| `make attribution` | reality gap: paper vs the backtest that authorised it |
| `make kill-stop REASON="..."` | stop trading right now |
| `make kill-status` | is the kill switch tripped, and why |

`make gate-acceptance` feeds the gate three deliberately overfit strategies and
all three must die — that is the gate proving it works.

---

## 5. Files you will actually touch

| Path | What it is |
|---|---|
| `CHEATSHEET.md` | this file |
| `CLAUDE.md` | the operating rules |
| `STATE.md` | where the project is right now (one page) |
| `TASKS.md` | what is still open |
| `docs/ARCHITECTURE.md` | how everything works and the maths |
| `docs/HISTORY.md` | the project's memory of its own mistakes |
| `mandate.yaml` | the operator-owned promotion criteria (verify, don't edit casually) |
| `config/` | universes, settings |
| `data/landing/` | immutable downloaded data |
| `data/logs/` | run logs (API, UI, ingest) |
| `.env` | secrets (never committed); `.env.example` is the template |

---

## 6. Golden rules in one line each

- Raw data never changes after it lands — re-running is always safe.
- `make verify` green is the definition of "done".
- `make daily` and a manual fetch cannot collide: the feed lock decides who goes.
- If a strategy fails `make gate`, it is dead. No tuning, no resubmission.
- If it is not in `STATE.md` or `TASKS.md`, it did not happen.
