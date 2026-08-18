# Runbook — resuming work in a fresh session

**Symptom.** The previous session ran out of context, crashed, or you are
coming back days later. Nothing is remembered.

**This is the designed-for case, not a failure.** ADR-002 states the rule: the
repository is the memory. If it is not written down, it did not happen.

---

## What you type

Paste this into a new session:

> Read `CLAUDE.md`, then `STATE.md`, then `TASKS.md`. Tell me where we are and
> what the next step is. Do not write code until I approve the plan.

That is the whole handoff. The three files are ~430 lines total and are
deliberately kept short enough to read in full.

---

## What the new session learns, and from where

| Question | Answered by |
|---|---|
| What sprint are we on, what works, what is broken? | `STATE.md` — one page, always current |
| What is done, what is next, what is blocked? | `TASKS.md` — the ledger |
| How am I supposed to work here? | `CLAUDE.md` — operating rules |
| **Why** is it built this way? | `docs/DECISIONS/ADR-*.md` |
| What did we already research, and what did it say? | `docs/RESEARCH/*.md` |
| This thing is broken — has it broken before? | `docs/RUNBOOKS/*.md` |
| What is fake or placeholder right now? | `docs/STUBS.md` |
| What are we assuming without proof? | `docs/ASSUMPTIONS.md` |

The ADRs matter most and are the least obvious. Without them a new session will
cheerfully re-litigate settled decisions — try to "fix" the universe by using a
published index list, or hand-write an alias map for renamed tickers. Both were
considered and rejected for recorded reasons.

---

## Why the data work survives a lost session

Every downloader is **idempotent and resumable**, driven by an append-only
manifest rather than by anything held in memory:

* Re-running downloads only what is missing. Nothing is re-fetched.
* An interrupted run leaves no partial files — writes are atomic
  (temp file, then rename), proven against a `SIGKILL` and an out-of-disk crash.
* The manifest records what landed and when (`knowledge_time`).

So the recovery procedure for any interrupted backfill is simply to run the
same command again:

```bash
make ingest-eod FROM=2015-01-01
make ingest-oi FROM=2020-01-01
make ingest-minute
make ingest-fundamentals
```

None of them need to know what a previous session was doing.

---

## The one thing that does NOT survive

**Background processes die with the session.** Check for orphans and restart
what matters:

```bash
pgrep -fl "backfill_|sync_cloud|disk_watchdog"
```

The disk watchdog in particular lives in the scratchpad, not the repo, so it is
lost on a new session and must be restarted by hand if a long backfill is
running. That is a known gap — see `STATE.md`.

---

## Keeping this true

The mechanism only works if `STATE.md` is honest, and it decays silently. On
2026-08-18 it still claimed a backfill was "running now" hours after it had
finished, and made no mention of the minute-bar or fundamentals work at all —
a fresh session would have been confidently wrong.

**Update `STATE.md` whenever a dataset changes state**, not only at sprint end.
It is the single highest-value file in the repository and the cheapest to let
rot.
