# ADR-037 — One strategy interface, three declarations

**Date:** 2026-08-21 · **Sprint:** fleet scale-up · **Status:** **PROPOSED**

Supersedes Decision 1 of ADR-036, which proposed *two* strategy interfaces.
On closer reading of the code that has to change, two is one too many.

---

## What the goal actually demands

"Any strategy type, any asset class, any timeframe" is a claim that invites
over-abstraction — a base class with twenty optional hooks, which is the switch
statement from `~/Documents/Trade` wearing a nicer coat. The useful move is to
find what genuinely varies and parameterise *that*, leaving the method signature
alone.

Three things vary, and only three:

| What varies | Example of the spread |
|---|---|
| **What it must see** | a cross-section of 250 daily bars ⟷ one instrument's minute bars ⟷ an option chain plus its underlying |
| **When it is asked** | every 21 trading days ⟷ every minute bar ⟷ on an expiry date |
| **What it may say** | target weights ⟷ a conditional entry with a bracket ⟷ a four-leg structure |

Nothing else does. Costs, calendars, lot sizes and settlement already vary by
instrument and are already time-versioned in the security master. So:

```python
class Strategy:
    requires: DataRequirement   # what I must see
    schedule: Schedule          # when to ask me
    def decide(self, view: MarketView) -> list[Intent]:  # what I want
```

One interface. Three declarations. A cross-sectional equity ranker, a minute-bar
pattern, a fundamental screen and an options spread differ in what they *declare*,
never in what they *implement*.

---

## Two concrete blockers, found by reading rather than assuming

These are the real reasons Tweezer is not a `Strategy` today. Neither is about
bracket exits, which is what T-3209 records.

**1. There are two bar types with no common ancestor.**

```
PanelRow(day: date,      symbol, close, volume, turnover, isin, open/high/low)
Candle  (ts:  datetime,          open, high, low, close, volume)
```

`MarketView.history` is `Mapping[str, Sequence[PanelRow]]`. A minute bar cannot
be expressed in it at all — not because of a missing field, but because
`PanelRow` is keyed on a **date** and a minute bar needs a **timestamp**. Tweezer
could not receive its own data through a `MarketView` even if it wanted to.

**2. The strategy boundary is keyed by symbol, not instrument.**

`CLAUDE.md` is unambiguous: *instrument joins use internal IDs only, never a
ticker.* The panel obeys this internally — `panel.py` keys on `InstrumentId` —
and then hands the strategy a `Mapping[str, ...]` of symbol strings.

For one asset class that is a latent bug. For several it is fatal: `RELIANCE`
names the equity, the future, and every option on it. A symbol-keyed view cannot
represent a multi-asset universe, and papering over it with `"RELIANCE24DECFUT"`
string conventions is how a backtest silently joins two different instruments.

**Both must be fixed before any of the generalisation is real**, and both are
invisible from the outside — which is why this ADR exists before any code.

---

## The three declarations

**`DataRequirement`** — what the strategy may see. Bars at a stated timeframe,
fundamentals, an option chain, reference data; over an instrument selector
(a universe, an explicit set, a filter by asset class); with a lookback.

Declared rather than inferred, for the same reason `lookback` already is: the
engine must not learn a strategy's internals (ADR-021). It buys three things —
the request is validated before the run rather than failing halfway through, the
loader fetches exactly what is needed, and **it is the enforcement point for the
firewall**: a strategy can only see what it declared, as of its decision time.

**`Schedule`** — when it is asked. `EveryBar(timeframe)`, `EveryN(n, timeframe)`,
`OnEvent(kind)`, `Continuous`. This deliberately decouples the data's timeframe
from the decision's cadence: a monthly rebalance may read daily bars, and a
daily decision may read minute bars.

**`Intent`** — what it may say. A sum type, not a dict:

- `TargetWeight(instrument, weight)` — what every strategy today emits
- `TargetQuantity(instrument, qty)` — absolute, for sized/notional strategies
- `ConditionalEntry(instrument, trigger, sizing, exits)` — Tweezer's shape
- `Structure(legs[...])` — multi-leg, filled atomically or not at all

Every intent carries its instrument id, strategy id, decision time and a
rationale string. Adding a fifth kind means extending RM, TM and the allocator —
it never means changing `decide()`.

`PortfolioStrategy` remains as a base class implementing `decide()` by wrapping
`target_weights()` into `TargetWeight` intents, so **no strategy that exists
today changes at all.**

---

## The trap this introduces: partial bars

At daily resolution "as of 2024-03-05" is unambiguous. At minute resolution it
is not, and the ambiguity is a lookahead bug that no existing test would catch.

A strategy deciding at 10:31:00 may see the bar that *closed* at 10:30:59. It may
not see the 10:31 bar, which has not finished forming — but that bar exists in
the stored file, complete, because history is written after the fact. The
firewall as built filters on `knowledge_time` at date granularity and would pass
it straight through.

So `MarketView` at a sub-daily timeframe must exclude the forming bar
structurally, the same way it excludes future rows: by not containing it. This
is the intraday equivalent of the download-time-as-knowledge-time defect
(correction 1 in `HISTORY.md`), and it will be equally invisible if it is not
designed against now.

---

## Declared is not supported

The interface will accept `AssetClass.CRYPTO` at a one-second timeframe. The
data for it does not exist, and a dropdown that offers it produces a confident
backtest over nothing.

So the system carries an explicit **capability matrix** — for each
(asset class × timeframe), whether data exists, its coverage, and its last
refresh — and both the API and the UI report *unsupported* rather than returning
an empty result. An empty result reads as "no trades found"; the truth is "this
was never measured".

Today that matrix is: equities daily (2,869 days, real), equities minute (13,501
files, real, Tweezer only), options chains (present, never wired to a strategy),
everything else absent.

---

## Cost if wrong

**Medium, and mostly paid up front.** `DataRequirement` and `Schedule` are cheap
to extend and cheap to get wrong — a missing kind is a compile error, not a
silent result.

`Intent` is the one to think about, because it is the vocabulary every downstream
component speaks. Getting its shape wrong means changing RM, TM, the allocator
and the attribution together. That argues for starting it deliberately small —
the four kinds above and no speculative fifth — since an unused variant is
harder to delete than a missing one is to add.

The instrument-key change is invasive but mechanical, and it is a correctness fix
this project already committed to in `CLAUDE.md`. It is not optional work that
generalisation happens to require; it is a rule currently being broken.
