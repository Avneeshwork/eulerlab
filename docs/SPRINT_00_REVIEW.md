# Sprint 0 — Scaffolding

**Status:** COMPLETE
**Branch:** sprint-00-scaffolding   **Commits:** 8
**Repo:** `github.com/Avneeshwork/eulerlab` (private)

All six acceptance criteria pass. This review was first written as PARTIAL,
because CI had never run; you approved the push, CI ran green, and the last
criterion closed. The history of that is left visible rather than tidied away.

---

## What now works (plain English, no jargon)

- **One command tells you if the repo is sound.** `make verify` runs five checks
  and prints a single table. You never need to run anything else to know whether
  to trust what I handed you.
- **The documentation gate has real teeth.** If I change code and don't document
  it, the build fails. I tested this deliberately, by committing a code-only
  change and watching it go red — output is quoted below. It's also tested
  permanently: `tests/test_docs_check.py` builds throwaway git repositories and
  checks both the pass and the fail case, so the gate can't quietly stop working.
- **Configuration can't be misspelled into silence.** Config files load into
  strict, frozen models. A typo'd key is an immediate error rather than a
  setting that looks applied and isn't. There's a test proving that
  `max_order_per_second` (missing the "s") is rejected — the exact class of typo
  that switches a safety limit off without anyone noticing.
- **`STATE.md` is machine-readable.** The next session can resume from it without
  guessing. If it ever drifts into unparseable prose, `make verify` goes red.
- **CI runs and passes.** Five gates on every push and pull request. First run:
  green in 13 seconds. One thing genuinely worth knowing — GitHub sends an
  all-zero base SHA for a brand-new branch, which would have broken a naive
  docs-check; the fallback path handled it, and that path is now exercised for
  real rather than only in theory.

Nothing trades. There is no market data, no downloader, no database, no
backtester, no strategy, no broker connection. Sprint 0 built the thing that
makes every later sprint checkable in two minutes. That is all it built.

## How to check it yourself (2 minutes)

```bash
make verify
```

Expected output — five rows, all green:

```
CHECK       RESULT   DETAIL
lint        PASS     0 issues, format clean
types       PASS     0 errors in 11 files
tests       PASS     27 passed
docs-check  PASS     all src changes have docs
state       OK       Sprint 0 complete, next: Sprint 1 — NSE EOD ingest

verify OK: 5 of 5 checks green
```

**Optional, if you want to see the docs gate bite** — this is the transcript from
when I tested it deliberately:

```
$ git commit -m "test: deliberate src-only change to prove docs-check fails"
$ make docs-check
docs-check FAILED — 1 change(s) touched src/ with no docs:
  commit 3da33eb test: deliberate src-only change to prove docs-check fails
    touched: src/eulerlab/__init__.py
    no change under docs/ or a root *.md
```

That commit was removed immediately; it is not in the history.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| `Order` model — 4 fields and `algo_id`, nothing more | Reserves the exchange's `algo_id` field before the OMS exists. 5 minutes now; a week of migrations later. **Not the real order schema** | 19 |
| `max_orders_per_second: 5` — a number nothing reads | The rate governor is a config key with no enforcement, because there is no execution system yet. Present so the compliance sprint is a config change, not a redesign | 19 enforced, 29 confirmed |
| `static_ip: null` | Placeholder. The real value is a fixed IP registered with your broker, which needs a VPS and an account first | 29 |
| `region: ap-south-1` | Written down as the intent. No cloud account exists; nothing validates the string | 2 |

Full list with detail: `docs/STUBS.md`.

## What I could not verify

- **Every market-structure fact in this repo is unverified.** Lot sizes, expiry
  days, settlement rules, the ~10 orders/sec regulatory threshold — all of it
  currently comes from `docs/quant_platform_playbook.md`, which states in its own
  header that it must be re-verified against primary circulars. I have not
  fetched a single SEBI, NSE or BSE circular yet. These are logged as A-001,
  A-002, A-003, A-005 and A-006 in `docs/ASSUMPTIONS.md` with recheck dates.
  **Two are due before the sprints that depend on them:** expiry days before
  Sprint 2, lot sizes before Sprint 3.
- **I have not tested the pre-commit hooks on a failing case.** They passed on
  clean files. I did not deliberately introduce a lint error to watch a commit
  get blocked, the way I did for docs-check.
- **Kite Connect's rate limits are unchecked.** Sprint 2 assumes a 5-second
  full-chain snapshot is permitted. I have not read Kite's API documentation to
  confirm it. Logged as A-008, and it is the first task of Sprint 2 — before any
  recorder code, because if it is false the design changes.

## Decisions you made

All four answered on 2026-08-18. Recorded in `STATE.md`; the data-source choice
also got an ADR because it is the project's first recurring cost.

1. **Private GitHub repo — yes.** Created at `Avneeshwork/eulerlab`, both
   branches pushed, CI green on run `32088448395`. This closed the last Sprint 0
   criterion. While there, I bumped `actions/checkout` v4→v7 and
   `astral-sh/setup-uv` v5→v10 — the first run warned that both were pinned to a
   deprecated Node runtime.

2. **NSE end-of-day history from 2015-01-01.** ~11 years. Extending later is
   cheap because the downloader is idempotent.

3. **Zerodha Kite Connect only, ₹500/mo.** Recorded as ADR-004. You declined the
   two-source option; noted as an accepted trade-off, not an oversight — a single
   feed has nothing to cross-check against, so vendor errors will have to be
   caught by the no-arbitrage checks in Sprint 7 instead of by disagreement
   between sources. Adding Dhan later costs nothing but integration work, and
   ADR-004 records the trigger for revisiting: the quality engine flagging
   anomalies one source cannot adjudicate.
   **Two things need you before Sprint 2:** a Kite Connect account with an API
   key issued (this has lead time — start it now), and confirmation that Kite
   permits a 5-second full-chain snapshot. I will check the second myself as
   Sprint 2's first task.

4. **Mumbai VPS before Sprint 2.** Not yet provisioned — that is an action for
   you. ~₹500–900/mo.

**Committed run rate once both are live: ₹1,000–1,400/mo.** Today it is ₹0.

## Reading added for you

Full list with the "why" for each: `docs/READING/index.md`.

- **Lookahead and survivorship bias** (MUST, 60 min) — needed before Sprint 4,
  where you approve the firewall that prevents both. You'll be judging whether
  ~15 adversarial tests test the right thing; that's not possible without knowing
  what the attacks look like. This is the single most valuable hour of reading in
  the whole project.
- **Idempotency, and why raw data is immutable** (SHOULD, 20 min) — needed for
  Sprint 1, whose acceptance test is that running the downloader twice downloads
  nothing the second time. Covered in `docs/GLOSSARY.md`; no external reading.
- **Point-in-time data, and why symbols are never join keys** (SHOULD, 30 min) —
  needed for Sprint 3. It's §1.1–1.2 of the playbook you already have.
- **Nothing at all for Sprint 2.** That sprint needs a VPS and a data source
  decision, not reading.

## Next sprint

**Sprint 1 — NSE EOD ingest.** A downloader that pulls bhavcopy and F&O bhavcopy
into an immutable landing zone: idempotent, resumable, rate-limited, with a
missing-day report that tells a market holiday apart from a failed download.
Before writing any of it I'll fetch and document the actual NSE archive URLs and
file schemas into `docs/RESEARCH/002-nse-archive-schemas.md` — that will be the
first thing in this repo verified against a primary source rather than the
playbook.

You verify it by running `make ingest-eod FROM=2015-01-01` twice. The second run
must download nothing and say so.
