# Sprint 09 — cost model
**Status:** PARTIAL — the model is built, internally consistent and matches
the one published worked example, but its acceptance criterion needs your real
contract notes and cannot pass without them

## The thing I need from you

The build plan verifies this sprint by *"reproducing 20 of your real contract
notes to the paisa"*. I don't have any, and I did not substitute invented
ones — a cost model validated against figures I made up would be worse than
no model, because it would look verified.

```bash
cp config/contract_notes.example.json config/contract_notes.json
```

Fill in the figures from any real broker contract notes — **5 would already be
very useful**, 20 passes the gate. `make check-costs` then compares every line
of the model against every line of the note, to the paisa, and tells you
exactly which one disagrees. The file is gitignored.

## What now works (plain English, no jargon)

- **You can ask what any trade actually costs**, itemised the way a contract
  note itemises it: brokerage, STT, stamp duty, exchange charge, SEBI fee,
  GST. Not a blended "0.1% round trip", because that number is wrong in both
  directions depending on the instrument.

- **Each charge lands on the leg that really pays it.** STT on intraday and
  futures is sell-side only; stamp duty is buy-side only; GST is 18% of
  *brokerage plus exchange fees*, never of the trade value. Averaging the legs
  loses precisely the asymmetry that makes a high-turnover strategy expensive,
  and applying GST to turnover would overstate costs about a thousandfold.

- **The rates are dated, because they changed while our data was being
  recorded.** Futures STT was 0.0125% until October 2024, then 0.02%, and
  0.05% from April 2026 — four times higher across a history we hold. A 2016
  trade is now costed at 2016 rates. If a date falls before the schedule
  starts, it refuses to answer rather than quietly using later rates.

### The finding that matters most: the playbook was wrong, and used to be right

`docs/ASSUMPTIONS.md` A-005 said *"STT on option exercise is charged on
notional, not premium."* That was true until 31 August 2019 and false
afterwards — the playbook recorded a fact that had expired.

The size of it: on the published example — one lot of 50, strike ₹17,300,
settlement ₹17,350, so ₹2,500 of profit —

| Rule | STT | Share of the profit |
|---|---|---|
| From 2019-09-01, on intrinsic value | **₹3.75** | 0.15% |
| Before 2019-09-01, on notional | **₹1,084.38** | **43%** |

This is the well-known "STT trap", and it is why traders let in-the-money
options expire worthless rather than exercise them. **Both rules are
implemented**, chosen by trade date, because the old one governs the first
four and a half years of our own price history. Any options backtest over
2015–2019 that ignored it would overstate returns on every expiry it held.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 627 tests
```

```bash
make check-costs
```

Expected: four green checks and one PARTIAL naming the missing contract notes.
The `STT trap` line prints ₹1,084.38 against ₹3.75 for the same expiry — that
is the whole finding in one line.

## What is fake right now

| Thing | Why | Removed when |
|---|---|---|
| Every rate is from a secondary source — A-016 | NSE's own STT page and circular FATAX73524 both timed out or would not decode on repeated fetches. Rates come from Zerodha, ClearTax and ICICI Direct summaries that agree with each other and reproduce a published worked example exactly | your contract notes, or a successful primary fetch |
| Pre-2024 F&O rates are "earliest known", not verified as contemporaneous | 0.0125% / 0.0625% are consistently reported as "prior to October 2024" but I could not find when they took effect. A 2016 backtest uses them as a floor | needs the older CBDT notifications |
| No slippage or market impact yet | The square-root impact law and the Amihud calibration from Sprint 8 are not wired in. The statutory charges are the larger and more certain part, so they came first | next session |
| Brokerage defaults to Zerodha's schedule | Configurable, and the only line here that is a commercial choice rather than a statutory rate | it is already a parameter |

## What I could not verify

- **Whether the model is right.** Four internal checks pass and one published
  example matches exactly, which is necessary and nowhere near sufficient.
  Only a real contract note settles it.
- **The other half of A-005** — that index options are cash-settled on a
  30-minute average and single-stock options are physically delivered. Still
  unverified; only the STT clause was resolved.

## Decisions I need from you

1. **Can you supply contract notes?** Option A: yes — any 5–10, and the gate
   becomes meaningful immediately. Option B: no — then A-016 stands and every
   backtest carries an unverified cost line.
   **My recommendation: A, strongly.** This is the cheapest verification in
   the project: a few files you already have, against a gate that is already
   written and will name the exact line that disagrees.

2. **Impact model before or after the backtester?** Option A: finish Sprint 9
   with slippage and square-root impact now. Option B: move to Sprint 10 and
   add impact when the backtester can actually exercise it.
   **My recommendation: B.** Impact only matters at size, and there is no
   position sizing yet to give it a participation rate. Statutory costs are
   the larger, more certain part and they are done.

## Reading added for you

- **Indian transaction taxes** (MUST, 30 min) — assigned for this sprint.
  `docs/RESEARCH/013-indian-transaction-costs.md` has every rate with its
  source and fetch date, plus the 2019 exercise change worked through.
- **Square-root impact law** (SHOULD, 20 min) — deferred with the impact
  model itself; read before Sprint 10 if you pick option A above.

## Next sprint

Sprint 10 — Tier A vectorised backtester. Fast, approximate, conservative,
for screening only. It will consume this cost model directly, which is the
first time these numbers meet a strategy.
