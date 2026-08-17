# Sprint 0 — Scaffolding

**Status:** PARTIAL
**Branch:** sprint-00-scaffolding   **Commits:** 5

**Why PARTIAL and not COMPLETE:** one of the six acceptance criteria is unmet —
*"CI passes on a pushed branch."* There is no GitHub remote, so
`.github/workflows/ci.yml` has never executed. Everything else is done and
verified. This is question 1 below, and it is a one-minute fix once you decide.

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
- **CI is written** and runs the same five gates on every push and pull request.
  Unverified until pushed — see above.

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

- **CI has never run.** The workflow is written against the documented interfaces
  of `actions/checkout@v4` and `astral-sh/setup-uv@v5`. I have not seen it
  execute once. Until it does, "CI enforces the gates" is an assumption, logged
  as A-004.
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

## Decisions I need from you

1. **Create a private GitHub repo now?** This is the only thing standing between
   Sprint 0 and COMPLETE.
   *Option A:* I run `gh repo create` for a private repo and push the branch —
   CI runs, we find out whether the workflow actually works, and I close the last
   criterion in Sprint 1.
   *Option B:* stay local; CI stays unverified indefinitely.
   **My recommendation: A.** A CI config that has never run is not a safety net,
   it is a comment. It costs a minute now and it is the only unverified piece of
   Sprint 0. I have not done it already because pushing code to a hosted service
   is your call, not mine — say the word and it's done.

2. **How far back should Sprint 1 pull NSE end-of-day data?**
   *Option A:* from 2015-01-01 (the kickoff document's example, ~11 years).
   *Option B:* from 2010, for a longer sample covering more regimes.
   *Option C:* from 2020, faster to get running.
   **My recommendation: A.** 2015 gives enough history for meaningful regime
   subsampling without a multi-hour first download. It is also cheap to extend
   later — the downloader is idempotent, so widening the range re-fetches only
   the new days.

3. **Which live data source for the Sprint 2 options recorder?** The kickoff doc
   says I'd ask this in the Sprint 1 review, but I'm asking now because broker
   account approval has lead time and every day the recorder isn't running is
   option-chain history that cannot be bought later at any price.
   *Option A:* Dhan — free API.
   *Option B:* Zerodha Kite Connect — ₹500/mo, best documented.
   *Option C:* both — ₹500/mo total.
   **My recommendation: C if you already hold both accounts, otherwise B.** Two
   independent sources let each one check the other, and cross-source
   disagreement is the single most effective data-bug detector there is — it
   catches the vendor errors that otherwise show up months later disguised as
   alpha. If you hold neither account, start the applications this week
   regardless of which you pick.

4. **Do you want the Mumbai VPS provisioned before Sprint 2, or should I plan
   Sprint 2 to run the recorder on your laptop first?**
   *Option A:* VPS (~₹500–900/mo) before Sprint 2.
   *Option B:* laptop first, move to the VPS later.
   **My recommendation: A.** The recorder must run unattended 09:15–15:30 IST
   every trading day, and a laptop that sleeps, loses wifi, or gets closed
   produces a history with holes in it. Holes are the one defect you cannot
   repair afterwards. ₹500/mo is the cheapest insurance in this entire project.

Questions 1 and 3 block progress. Questions 2 and 4 I can proceed on with my
recommended defaults if you'd rather not decide now — say "go with your
defaults" and I'll note the choice in `STATE.md`.

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
