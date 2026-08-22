# 020 — Where intraday bars come from, and what happens when the token expires

**Question.** The intraday strategies coded in `019` need minute bars, and the
operator asked for a free source and an unattended daily update. What is
actually available, and what does each source really provide?

## Sources

| Source | Checked | Result |
|---|---|---|
| Zerodha Kite historical API | 2026-08-22, live call | **Works.** 184,389 bars for 2 symbols over 1 year, 0 failed. Session minted 2026-08-22T04:08Z |
| Yahoo Finance via `yfinance`, NSE symbols (`RELIANCE.NS`) | 2026-08-22, live call | **Works, with hard limits measured below** |

## Findings

### Kite is the source of record, and it cannot renew itself

`make ingest-minute` works and the token in `.kite_session.json` is valid. The
constraint is structural rather than technical: **the token expires at 6 AM and
reminting it requires an interactive login**, so an unattended job can never
renew it. A daily job at 19:30 gets minute bars only on days the operator
logged in.

The failure mode that mattered was not the expiry — it was that an expired
token made the ingest do nothing *quietly*. `make kite-fresh` now compares the
token's mint date against today and fails with the command to fix it, so a
missed day is a line in `data/logs/daily.log` naming the cause rather than an
absence noticed a month later.

### Yahoo Finance is a real fallback, and the limits are the point

Measured on `RELIANCE.NS`, 2026-08-22 — not quoted from documentation:

| Interval | Period requested | Rows returned | Span |
|---|---|---|---|
| `1m` | `5d` | 1,805 | 2026-08-17 09:15 IST to 2026-08-21 15:15 IST |
| `5m` | `1mo` | 1,694 | 2026-07-22 to 2026-08-21 |
| `1d` | `1y` | 251 | 2025-08-21 to 2026-08-21 |

Timestamps come back in IST and align to the NSE session, so the bars are the
right object. No authentication, no key, no expiry.

**The limit is history, not access.** One-minute data reaches back roughly five
trading days. That is useless for backtesting a signal over months, and
sufficient for keeping a rolling window current — so it is a *continuity*
fallback, not a replacement. A rolling daily fetch would accumulate history
going forward but cannot recover the past.

## Decision

Kite stays the source of record. `make daily` now runs `daily-minute` behind
the freshness gate, and adds the Binance crypto archive, which needs no
authentication at all and so is the one intraday source that genuinely updates
unattended.

Yahoo is **recorded but not wired**. Building a second ingest path costs a
second set of symbol mappings, a second adjustment convention and a second set
of quality checks, for data that cannot backfill. It is written down here so
the option is known and the limits are measured — the reason it is not built is
a decision, not an oversight.

**Confidence.** High on both; each was a live call today, not a documentation
claim.

## Open questions

- The gate makes a stale token visible but nobody is watching the log. A
  Telegram token already exists in `.env` for other alerts; routing the daily
  job's failures there would close the loop.
- Whether five days of Yahoo minute bars accumulated daily eventually becomes a
  usable history depends on it never missing a day, which is exactly the
  property an unattended job cannot promise. Worth measuring before relying on.
