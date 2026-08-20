# ASSUMPTIONS — everything this project rests on but has not verified

Every entry has a recheck date. Anything here that turns out to be wrong
invalidates whatever depends on it, so the "Depends on it" column matters as
much as the claim.

Regulatory and contract-spec facts change often. Treat a passed recheck date as
a red flag, not a formality.

**How to use this file:** `grep -rn "ASSUMPTION:" src/` finds every place in the
code that rests on one of these.

---

| ID | Claim | Source | Confidence | Recheck by | Depends on it |
|---|---|---|---|---|---|
| A-001 | SEBI's retail algo framework treats roughly **10 orders/sec/exchange/client** as the boundary of the registered-algo regime | `docs/quant_platform_playbook.md` §0.1 — an operator-supplied reference document, **not** a primary circular | Low | 2026-11-30 | `config/execution.yaml` default of 5; the whole "OPS governor is cheap insurance" argument |
| A-003 | One weekly index expiry per exchange: **Nifty 50 weekly on Tuesday (NSE)**, **Sensex weekly on Thursday (BSE)**; Bank Nifty / FinNifty / Midcap Select weeklies discontinued | **Largely confirmed 2026-08-18** from Kite's instrument master: 17/18 Nifty expiries are Tuesdays (one is a Monday), 19/19 Sensex are Thursdays. The discontinuation claim is still unverified | Medium | Sprint 3 | Expiry handling. **Never compute expiry from a weekday rule** — the Monday exception is why |
| A-005 | Indian index options are cash-settled on the last-30-minute average; single-stock options are physically delivered; **STT on option exercise is charged on notional, not premium** | See Resolved | — | — | — |
| A-006 | Onshore crypto: 30% flat VDA tax + cess, 1% TDS on transfers, no loss set-off | `docs/quant_platform_playbook.md` §0.3 | Low | Before any crypto backtest | Whether high-turnover crypto strategies are viable at all — this is a cost input, not paperwork |
| A-007 | The options recorder will use 50–200 MB/day of disk | `docs/sprint_01_kickoff.md` Sprint 2 criteria | Low | Sprint 2, day 1 | VPS sizing and the disk-full runbook |
| A-009 | The NSE legacy bhavcopy archive stops being published between 2024-06-03 and 2024-09-02 | Probed directly 2026-08-18 (research note 002). Search results attribute it to NSE Circular 62424 w.e.f. 2024-07-08, but **that circular was not fetched** | Medium on the range, low on the exact date | Before Sprint 1 ships | The format-selection logic in the downloader. Mitigated by probing rather than hardcoding the date |
| A-013 | Kite's tick stream updates all 4,138 subscribed strikes often enough for 5-second snapshots to be meaningful | The docs specify no tick frequency or throttling. Illiquid far-wing strikes may simply not trade | Low | **Sprint 2, first live session** | Whether snapshots of the wings are real or stale. Mitigation: a per-instrument staleness marker is mandatory, not optional |
| A-011 | Skipping weekends misses no trading sessions | NSE runs occasional special sessions (Muhurat on Diwali) that need not fall on a weekday. The backfill skips weekends by default to avoid ~1,100 wasted request-days | Medium | Before Sprint 3 (calendars) | Completeness of the history. Mitigated: `--include-weekends` sweeps for them, and the ANOMALY check would flag a one-segment weekend file |
| A-012 | NSE's holiday endpoint covers only the current year | Observed 2026-08-18: `api/holiday-master?type=trading` returned 2026 entries per segment, with no year parameter found | Medium | Before Sprint 3 | Whether historical closures can ever be *confirmed* rather than *likely*. The report labels them honestly either way |

---

| A-014 | NSE publishes the EOD bhavcopy and participant-OI files on the evening of the trade date, by 20:00 IST | **Not sourced from any NSE circular.** One measurement bounds it: our single same-day capture of participant OI was fetched at 19:09 IST on 2026-08-18, so that feed at least is out by then. The other segments have no same-day capture and therefore no evidence at all | Low on the hour, high on the day | Before any intraday strategy, or Sprint 9 | Every backtest's `knowledge_time`. Mitigated three ways: the assumed hour is deliberately late, so the error withholds data rather than leaking it; `from_manifest_row` raises if a file was fetched before its assumed publication, which is how the wrong hour was found; and a daily strategy is unaffected by the hour entirely |
| A-015 | The rights-issue adjustment factor is `TERP/P`, and the rights issue price is face value plus the stated premium | **Formula not read from an NSE primary source.** Both official NSE pages timed out on fetch and circular FAOP56050 would not decode. Taken from a broker's summary of the NSE methodology (Zerodha, fetched 2026-08-19) and cross-checked algebraically against the standard theoretical ex-rights price — the two are identical, which is why this is medium-high rather than low. The issue-price rule **is** validated on primary data: Reliance's 2020 issue was 1:15 at ₹1,257, and the feed gives faceVal 10 + premium 1247 | Medium-high | Before Sprint 9 (cost model), or before any strategy holds a name through a rights issue | Every rights-issue adjustment factor. 276 of 25,713 actions (1.1%). Mitigated: no factor is produced when the issue price is at or above market, and the formula is unit-tested against the worked TERP example |
| A-016 | Every STT, stamp-duty, exchange and GST rate in `costs/schedule.py` | **Not from a primary source.** NSE's STT page and circular FATAX73524 both timed out or would not decode on repeated fetches. Rates come from broker and tax-portal summaries (Zerodha, ClearTax, ICICI Direct) that agree with one another, cross-checked against a published worked example the model reproduces exactly | Medium-high | Before live trading, or whenever a Budget changes rates | Every backtest's cost line. Mitigated: `make check-costs` reports PARTIAL rather than green until reconciled against real contract notes, and the schedule is data so a correction is one row |
## Resolved

| ID | Claim | Resolution |
|---|---|---|
| A-005 | STT on option exercise is charged on notional, not premium | **Resolved 2026-08-19 — TRUE until 2019-08-31, FALSE since.** The playbook recorded a fact that had expired. Effective 2019-09-01 STT on exercise is charged on **intrinsic value** (settlement minus strike), not the notional settlement value. The difference is a factor of ~289 on a near-the-money expiry: Rs 1,084 vs Rs 3.75 on Zerodha's published example. **Both rules are implemented** and selected by trade date (ADR-020), because the notional rule governs the first four and a half years of our price history. The cash-settlement and physical-delivery halves of A-005 remain unverified and are still open. |
| A-002 | Index lot sizes are periodically reset and must be time-versioned | **Resolved 2026-08-19 — CONFIRMED from primary data.** Built a contract registry from 140 monthly F&O bhavcopy snapshots (2.29M contracts, 5.7M contract-days) and read NIFTY's lot size through time: **50** (2024-03), **25** (2024-11), **75** (2025-03), **65** (2026-03). The playbook's claimed 25→75→65 is right as far as it goes and omits the earlier 50. Lot size is now derived from our own data rather than assumed, and `ContractRegistry.lot_size_at()` answers it per date. |
| A-000 | `docs/quant_platform_playbook.md` exists and is the reference design | **Resolved 2026-08-17.** Operator supplied the file; it is committed. Sprint 0 opened without it and did not depend on it. |
| A-010 | NSE's terms permit automated downloading of its public archive files | **Resolved 2026-08-18 — FALSE.** The Terms of Use prohibit *"any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)"*. Read directly at `nseindia.com/static/nse-terms-of-use`. robots.txt is permissive but does not override written terms. **Superseded by ADR-006:** the operator was shown this and decided to proceed anyway, knowingly. The prohibition is real and unchanged; what changed is that the risk has been accepted and recorded rather than overlooked. |
| A-008 | Kite permits a 5-second full-chain snapshot | **Resolved 2026-08-18 — conditionally.** Not by polling: 4,138 contracts at 500/call and 1 req/sec is a 9-second pass. Yes by WebSocket: 3,000 instruments/connection × 3 connections, subscribe once and sample in-memory state on a local timer. Research note 003. |
| A-004 | The CI workflow is correct | **Resolved 2026-08-18.** Pushed to `Avneeshwork/eulerlab`; run 32088448395 passed all five gates in 13s. The all-zero `DOCS_CHECK_BASE` that GitHub sends for a new branch exercised the fallback path in `docs_check.py`, which behaved as designed. |
| A-018 | The kill-switch limits in `config/killswitch.yaml` are appropriate | **UNVERIFIED, and knowingly so.** ₹10,000 daily loss, 200 orders/day, 5 consecutive rejections, ₹500,000 per position, 3 unresolved orders. Every one is a round number chosen to be conservative against the 1–2% of capital Sprint 31 puts at risk; none is derived from a measured distribution. The loss limit is the one that matters — set too tight it halts on an ordinary day, set too loose it does not halt at all. **Recheck: after four weeks of paper trading**, from the observed daily P&L distribution rather than from intuition. `# ASSUMPTION:` noted in the config file itself. |
| A-019 | The hosted providers in `config/llm.yaml` offer usable free tiers | **UNVERIFIED, and deliberately not claimed.** OpenRouter's `:free` models, Groq's free tier and similar are advertised by their vendors; none has been tested from this machine and none is quoted as a specific quota anywhere in the code. Free-tier limits change without notice. What *is* relied on is the request shape — `POST {base_url}/chat/completions` with `{model, messages}` — which is the common OpenAI-compatible interface all of them publish. The only provider with genuinely no quota is `ollama`, because it runs locally. **Recheck: whenever a hosted provider is actually used.** Nothing in the system depends on any of them; the default needs no key at all. |

---

## Standing caveat on the reference documents

`docs/quant_platform_playbook.md` states in its own header that all regulatory
and tax details are as of August 2026 and must be re-verified against primary
sources before being relied on. Every A-00x entry above that cites it inherits
that caveat. **No number from these documents should reach a cost model, a
margin calculation, or a contract spec without a primary source first.**
