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
| A-002 | Index derivative **lot sizes** are periodically reset to hold notional in a ₹15–20 lakh band, and have changed repeatedly (Nifty 50 25 → 75 → 65; Bank Nifty 15 → 35 → 30) | `docs/quant_platform_playbook.md` §0.1 | Low | **Before Sprint 3** | The security master's time-versioned lot size design. The *design* is right regardless; the specific numbers are not to be used |
| A-003 | One weekly index expiry per exchange: **Nifty 50 weekly on Tuesday (NSE)**, **Sensex weekly on Thursday (BSE)**; Bank Nifty / FinNifty / Midcap Select weeklies discontinued | `docs/quant_platform_playbook.md` §0.1 | Low | **Before Sprint 2** | The options recorder's snapshot schedule; every expiry-cycle strategy later |
| A-005 | Indian index options are **cash-settled** on the average underlying over the last 30 minutes; **single-stock options are physically delivered**; STT on option exercise is charged on notional, not premium | `docs/quant_platform_playbook.md` §0.1 | Low | Before Sprint 9 (cost model) | The cost model, and whether near-the-money expiry positions are tradeable at all |
| A-006 | Onshore crypto: 30% flat VDA tax + cess, 1% TDS on transfers, no loss set-off | `docs/quant_platform_playbook.md` §0.3 | Low | Before any crypto backtest | Whether high-turnover crypto strategies are viable at all — this is a cost input, not paperwork |
| A-007 | The options recorder will use 50–200 MB/day of disk | `docs/sprint_01_kickoff.md` Sprint 2 criteria | Low | Sprint 2, day 1 | VPS sizing and the disk-full runbook |
| A-008 | Kite Connect permits a 5-second full-chain snapshot for Nifty and Sensex within its rate limits | Partly informed 2026-08-18: Kite docs give **1 req/sec** for quotes and 3/sec for historical (`kite.trade/docs/connect/v3/exceptions/`). Whether one quote call can carry a full chain, and at what instrument count, is **still unchecked** | Low | **First task of Sprint 2** | The entire Sprint 2 recorder design. If false, the sprint stalls until a source switch |
| A-009 | The NSE legacy bhavcopy archive stops being published between 2024-06-03 and 2024-09-02 | Probed directly 2026-08-18 (research note 002). Search results attribute it to NSE Circular 62424 w.e.f. 2024-07-08, but **that circular was not fetched** | Medium on the range, low on the exact date | Before Sprint 1 ships | The format-selection logic in the downloader. Mitigated by probing rather than hardcoding the date |
| A-010 | NSE's terms permit automated, rate-limited downloading of its public archive files | **Not reviewed.** No terms page was read | Low | **Before the first full 11-year backfill run** | Whether Sprint 1's downloader should run at all at scale |
| A-011 | Skipping weekends misses no trading sessions | NSE runs occasional special sessions (Muhurat on Diwali) that need not fall on a weekday. The backfill skips weekends by default to avoid ~1,100 wasted request-days | Medium | Before Sprint 3 (calendars) | Completeness of the history. Mitigated: `--include-weekends` sweeps for them, and the ANOMALY check would flag a one-segment weekend file |
| A-012 | NSE's holiday endpoint covers only the current year | Observed 2026-08-18: `api/holiday-master?type=trading` returned 2026 entries per segment, with no year parameter found | Medium | Before Sprint 3 | Whether historical closures can ever be *confirmed* rather than *likely*. The report labels them honestly either way |

---

## Resolved

| ID | Claim | Resolution |
|---|---|---|
| A-000 | `docs/quant_platform_playbook.md` exists and is the reference design | **Resolved 2026-08-17.** Operator supplied the file; it is committed. Sprint 0 opened without it and did not depend on it. |
| A-004 | The CI workflow is correct | **Resolved 2026-08-18.** Pushed to `Avneeshwork/eulerlab`; run 32088448395 passed all five gates in 13s. The all-zero `DOCS_CHECK_BASE` that GitHub sends for a new branch exercised the fallback path in `docs_check.py`, which behaved as designed. |

---

## Standing caveat on the reference documents

`docs/quant_platform_playbook.md` states in its own header that all regulatory
and tax details are as of August 2026 and must be re-verified against primary
sources before being relied on. Every A-00x entry above that cites it inherits
that caveat. **No number from these documents should reach a cost model, a
margin calculation, or a contract spec without a primary source first.**
