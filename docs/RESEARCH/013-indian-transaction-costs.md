# 013 — Indian transaction costs, and why they must be time-versioned

**Sprint:** 9 · **Date:** 2026-08-19 · **Confidence:** high on the current
rates and on the 2019 exercise change; medium on the rate history before 2024

## Question

What does a trade actually cost in India, and can a single rate table serve a
backtest that spans 2015–2026?

## Finding: no. STT rates changed repeatedly inside the backtest window

This is the finding that shapes the whole sprint. A flat rate table would be
wrong for most of the history it is applied to.

| Effective | Futures (sell) | Options premium (sell) | Options exercise |
|---|---|---|---|
| …to 2024-09-30 | 0.0125% | 0.0625% | 0.125% |
| 2024-10-01 | 0.02% | 0.10% | 0.125% |
| 2026-04-01 | **0.05%** | **0.15%** | **0.15%** |

Equity rates did *not* change: delivery 0.1% on both sides, intraday 0.025%
on the sell side only.

Sources: [ICICI Direct on the 2024 change](https://www.icicidirect.com/research/equity/finace/new-stt-rules-in-futures-and-options-trading),
[ClearTax](https://cleartax.in/s/securities-transaction-tax-stt),
[Zerodha's STT article](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated),
all fetched 2026-08-19.

The consequence for this codebase: the cost model is a **time-versioned
registry**, the same shape as lot sizes in Sprint 3 (A-002), not a constants
file. A backtest of a 2018 strategy that pays 2026 STT is not conservative —
it is wrong, and wrong by a factor of four on futures.

## Finding: A-005 is wrong, and was right until 2019

`docs/ASSUMPTIONS.md` A-005, taken from the playbook, says *"STT on option
exercise is charged on notional, not premium."*

**Effective 1 September 2019, STT on exercise is charged on the intrinsic
value** — the difference between settlement price and strike — not on the
settlement price. Before that date it *was* charged on the notional
settlement value, so the playbook recorded a fact that had expired.

The magnitude of the difference is why this matters. Zerodha's worked example:
one lot of 50, strike ₹17,300, spot ₹17,350. Intrinsic value ₹2,500, so STT
is 0.15% × 2,500 = **₹4**. On the notional ₹867,500 it would have been
**₹1,301** — a factor of **325**.

Sources: [Zerodha Z-Connect, "STT Trap - Options Expiry"](https://zerodha.com/z-connect/trending/stt-options-nse-bse-mcx-sx),
[Motilal Oswal](https://www.motilaloswal.com/learning-centre/2020/2/effect-of-stt-on-option-exercise),
[Rupeezy](https://rupeezy.in/blog/stt-calculation-changed-for-options), fetched 2026-08-19.

The pre-2019 rule is not a historical curiosity for us: it applies to the
first four and a half years of our own price history, and it is the origin of
the well-known "STT trap" where letting an ITM option expire cost more than
the profit. A backtest of a 2016–2019 options strategy that ignores it will
overstate returns on every expiry.

## Finding: the other charges are small individually and not negligible together

- **Stamp duty** — buy side only, 0.015% on delivery, 0.003% on intraday and
  futures, 0.003% on options. Buy-side-only matters: applying it to both legs
  doubles it.
- **Exchange transaction charge** — NSE, roughly 0.00297% on cash and 0.0035%
  on options premium.
- **SEBI turnover fee** — ₹10 per crore, i.e. 0.0001%.
- **GST** — 18%, and levied on *brokerage plus transaction charges*, not on
  the trade value. Applying 18% to turnover would overstate costs by orders
  of magnitude.

## Decision

Build the cost model as a time-versioned schedule keyed by effective date,
queried with the trade date, so a 2016 trade pays 2016 rates. Resolve A-005 as
**FALSE since 2019-09-01, TRUE before it**, and implement both rules.

## What I could not verify

- **The primary NSE circular and NSE's own STT page both timed out** on repeated
  fetches; circular FATAX73524 (2026-03-31) would not decode. Every rate here
  comes from broker and tax-portal summaries that agree with each other, not
  from the notification itself. Recorded as A-016 with a recheck date.
- **STT rates before 2024** for F&O. The 0.0125% / 0.0625% pair is consistently
  reported as "prior to October 2024" but I did not find when *those* took
  effect, so any backtest before that point uses them as the earliest known
  rate rather than a verified contemporaneous one.
- **Brokerage** is broker-specific and configurable rather than researched;
  Zerodha's published schedule is the default.
