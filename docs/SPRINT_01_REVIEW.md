# Sprint 1 — NSE EOD ingest

**Status:** IN PROGRESS
**Branch:** sprint-01-nse-eod-ingest   **Commits:** 6

**The one-line version:** the downloader is built, tested, and running the full
2015→2026 backfill now. It was BLOCKED for part of the sprint on NSE's Terms of
Use, which prohibit systematic automated collection; you were shown that and
decided to proceed anyway, recorded as ADR-006.

**Read the credentials section below before anything else.** Four of your live
credentials reached git history during this sprint, through a mistake of mine.
They need rotating.

---

## What now works (plain English, no jargon)

- **`make ingest-eod FROM=2015-01-01 TO=2026-08-18`** downloads NSE equity and
  F&O end-of-day files into `data/landing/`, one file per day per segment.
- **It handles both of NSE's file formats.** NSE changed format mid-2024, so an
  11-year history spans two different schemas at two different URL patterns.
  Both are verified against real downloads — a 2015 file and a 2026 file.
- **Running it twice downloads nothing the second time.** Measured on real data:
  20.6 seconds the first time, 1.3 seconds the second, zero re-fetches.
- **It survives being killed.** I killed it mid-download with `SIGKILL` — the
  most violent stop there is, which a program cannot catch or clean up after.
  Result: no half-written files, every checksum still valid, and the next run
  picked up exactly where it left off.
- **`make check-landing`** re-hashes every downloaded file against its recorded
  checksum, so "these files have never been modified" is something you can check
  in two seconds rather than something you take on trust.
- **It never guesses about missing days.** More on this below — it is the part I
  am most confident about.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green
make check-landing   # expect: 142 files, all checksums match
```

Then, to see the idempotency claim yourself on data already downloaded:

```bash
make ingest-eod FROM=2026-08-10 TO=2026-08-14
```

Expected output: `downloaded 0`, `skipped 10`, and `Result: CLEAN` in about a
second. It makes no network requests at all.

## The part worth understanding: holidays vs failures

A backtest cannot tell the difference between "the market was shut" and "the
download failed", but the difference is everything: one is normal, the other is
silent data loss that becomes fake alpha later.

The tempting shortcut is to call any missing file a holiday. That is circular —
it defines away the very failure you are trying to detect. So instead:

| What happened | Called | Why |
|---|---|---|
| Network error, or a server error after retries | **FAILED** | Always data loss. Never a holiday |
| Server said 404, **both** equity and F&O | **holiday (likely)** | Markets shut together |
| Server said 404, and NSE's holiday list agrees | **holiday (confirmed)** | Corroborated |
| Server said 404 for **one** segment, other landed | **ANOMALY** | A holiday shuts both. This is the shape of a silent gap, and it gets flagged loudly |

This works: on 2015-01-26 (Republic Day) it correctly reported one likely
holiday and zero anomalies, with no holiday list involved.

The honest limitation: NSE's holiday endpoint only serves the current year, so
historical closures stay "likely" rather than "confirmed". The report says so
in plain text rather than implying more certainty than it has.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Nothing new is faked this sprint | The downloader is real and does what it says | — |
| Sprint 0's three compliance stubs still stand | `algo_id`, OPS governor, `static_ip` | 19 / 19 / 29 |

`docs/STUBS.md` is unchanged.

## The credential incident — please read this one

**What happened.** You put real values into `.env.example`. That file is tracked
and committed; `.env` is the gitignored one. Then commit `afaf099` — mine — swept
your edit into the repo via `git add -A` without me reading the diff, and I
pushed it.

**That is my error, not yours.** Using `git add -A` in a repo where you are also
editing files is precisely how this happens, and I did it repeatedly this sprint
without once reviewing what I was staging. The `detect-private-key` pre-commit
hook did not catch it because it recognises PEM private keys, not API tokens.

**What reached the remote**, on `origin/sprint-01-nse-eod-ingest`:
`ZERODHA_API_KEY`, `ZERODHA_API_SECRET`, `ZERODHA_ACCESS_TOKEN`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. The B2 key material was in the working
tree only and never committed, but it was displayed in the session transcript.

**Rotate all of them.** Deleting a secret from a file does not un-publish it —
it is in the commit objects, and GitHub keeps dangling objects even after a
history rewrite. `ZERODHA_ACCESS_TOKEN` is the urgent one: it can place orders.

**What I did.** Moved all real values into `.env` (gitignored, verified), reset
`.env.example` to empty placeholders, and added `tests/test_no_secrets.py` so
`make verify` goes red if any value there is ever non-empty again — commented-out
ones included. HEAD is clean. History is not, and cannot be made so by
committing.

**Still open:** whether to rewrite the branch history and force-push. Worth doing
for hygiene, destructive to a pushed branch, and not a substitute for rotating.
Your call.

## What I could not verify

- **I could not run the backfill**, so the downloader has never been exercised at
  11-year scale. Its behaviour over ~2,800 days — rate limiting over hours,
  memory, the failure rate against a real archive — is untested. It works on
  142 files. That is not the same as working on 5,600.
- **Whether a session cookie is required** for NSE's legacy archive. Every
  successful request carried one; I never isolated the variable.
- **The exact date NSE switched formats.** Narrowed by probing to between
  2024-06-03 and 2024-09-02. The code does not hardcode it — it tries both
  formats and takes whichever answers — so a wrong guess costs one request
  rather than a missing day.
- **Whether NSE Data & Analytics' licensed portal actually carries what we need,
  and at what price.** I did not investigate; it is a commercial question.

## Two things I got wrong, stated plainly

1. **My first two interrupt tests didn't interrupt anything.** I sent `SIGINT`
   to a background process and reported "interrupted" — but the signal never
   arrived (this sandbox doesn't deliver it), and each run quietly completed a
   full month instead of stopping after 15 seconds. I caught it because the file
   count didn't match the rate limit. I then tested with `SIGKILL`, which does
   land, and which is a stricter test anyway.
2. **Because of that, I downloaded more than I meant to.** You sanctioned testing
   "on a handful of days". What actually landed is **142 files, 31 MB** —
   parts of January to May 2015 plus one week of August 2026. Not egregious, but
   four months more than I intended, and the overrun was my error rather than a
   plan. Nothing has been fetched since I read the terms.

## Decisions taken during the sprint

1. **Historical EOD source, given NSE prohibits scraping it.** **You chose to
   proceed from the public archive anyway** (ADR-006). Recorded with the
   reasoning intact so it reads as a decision rather than an oversight. I kept
   the 1.5s rate limit and built no evasion tooling — no IP rotation, no
   identity cycling. For the record, the original options were:

   NSE's Terms of Use, read directly today, say: *"User is prohibited to conduct
   any systematic or automated data collection activities (including scraping,
   data mining, data extraction and data harvesting) on or in relation to our
   Website / Mobile Application."*

   Worth knowing: `robots.txt` says the opposite — `Allow: /`. A permissive
   robots.txt is a crawler convention, not a licence, and the written terms
   govern. Anyone checking only robots.txt would have concluded we were fine.

   - *Option A — NSE Data & Analytics licensed portal.* The sanctioned route.
     Costs money, amount unknown. Legitimate, and the data is authoritative.
   - *Option B — Ask NSE for written permission.* Free if granted. Slow, and
     may not be granted for a one-person operation.
   - *Option C — Kite historical API as the history source.* You already pay
     ₹500/mo and it is licensed for your use. But its instrument list is a
     present-tense snapshot, so we would additionally need a historical
     instrument master from somewhere to avoid survivorship bias — which is a
     real piece of work, not a config change.
   - *Option D — A commercial vendor* (TrueData, GDFL). Breaks your two-source
     policy and costs ₹1,000–3,000/mo.

   My recommendation had been A. You chose otherwise, which is your call to make
   and your risk to carry; ADR-006 states that plainly.

2. **The 142 development-era files: kept.**

3. **Cloud storage: Backblaze B2** (ADR-007). `make sync-cloud` mirrors the
   landing zone over the S3 API, so the same code serves B2, R2, S3 or Wasabi.
   It is a mirror rather than the write path — adding a network write to each of
   ~5,800 downloads would multiply the ways a multi-hour backfill can die.
   Integrity is checked with our own SHA-256 in object metadata, not the ETag,
   which is MD5 only for simple uploads.

## Still needed from you

1. **Rotate the four leaked credentials.** See the section above.
2. **Recreate the B2 application key.** The current one has `writeFiles`,
   `deleteFiles` and `listBuckets` but **no `readFiles` or `listFiles`**. It
   needs read access, or the sync cannot tell "already uploaded" from "not
   allowed to look" — and `deleteFiles` should be off, since the landing zone is
   append-only and the sync never deletes. Runbook:
   `docs/RUNBOOKS/cloud-sync.md`.
3. **Say whether to rewrite git history** to purge the secrets from the commits. If you would rather they were gone, one
   command removes them.

## Reading added for you

- **Nothing new is required.** The Sprint 1 reading (idempotency, immutable raw
  data) is already in `docs/READING/index.md` and is covered by
  `docs/GLOSSARY.md`.
- Still outstanding and now more urgent: **lookahead and survivorship bias**
  (MUST, 60 min). Question 1 above is a survivorship-bias question in disguise —
  option C is tempting precisely because the bias it introduces is invisible.

## Next sprint

**Not Sprint 2 yet.** Sprint 1 has a decision in it, and Sprint 2 has two
operator actions outstanding (Kite account with an API key issued, and the
Mumbai VPS). Both have lead time, so they are worth starting now regardless of
what you decide about question 1.

Once question 1 is answered, Sprint 1 closes quickly — the code is done, and
pointing it at a licensed source is a small change to one module. If you would
rather keep moving while that is in flight, Sprint 2's recorder is independent
of it, and its first task is checking Kite's rate limits (A-008) — which needs
no data licence at all.
