# GLOSSARY — plain English

For the operator. Every term that appears in a sprint review should be here. If
a review uses a word this file does not define, that is a bug in the review.

---

## The two that matter most

**Lookahead bias** — using information in a backtest that you could not actually
have had at that moment. Usually accidental: a data vendor quietly fills in a
revised number, or a calculation peeks one row forward. It is the most common
way a strategy looks brilliant on paper and loses money live. Sprint 4 builds a
firewall that makes it structurally impossible rather than merely discouraged.

**Survivorship bias** — testing today's list of companies against history. The
Nifty 50 of 2015 was not the Nifty 50 of today, and the difference is precisely
the companies that did badly enough to be removed. Testing on today's list
quietly assumes you knew in 2015 which firms would survive.

---

## Data

**Bitemporal** — every record carries two timestamps: `event_time` (when it
happened) and `knowledge_time` (when we could first have known it). Asking for
data "as of" a past date then returns what was actually knowable then. This is
the mechanism behind the lookahead firewall.

**Landing zone** — the folder where raw downloaded files land, unmodified,
forever. Never edited, never deleted. It exists so that when a bug is found in
the processing code — and one will be — everything downstream can be rebuilt
from scratch.

**Idempotent** — running it twice does the same thing as running it once. A
re-run of the downloader must fetch nothing and change nothing.

**Bhavcopy** — NSE/BSE's end-of-day file: every instrument's open, high, low,
close and volume for the day. Free from the exchange archives. The starting
point for Indian equity data.

**Point-in-time** — data stored as it was originally reported, including
later-revised values. The opposite of a current snapshot, which has quietly
overwritten history.

**Corporate action** — a split, bonus, dividend, merger or symbol change. Each
one puts a discontinuity in the price series that must be adjusted for, or the
strategy sees a 50% "crash" that was actually a 2-for-1 split.

---

## Testing a strategy

**Backtest** — running a strategy over historical data to see what it would have
done. Trustworthy only to the extent the simulation is honest about costs,
timing and fills.

**Tier A / Tier B backtester** — Tier A is fast, approximate and deliberately
pessimistic, used to screen thousands of ideas. Tier B is slow, event-driven,
and processes events in the same order the live system will. Only Tier B counts
for a promotion decision.

**Information Coefficient (IC)** — how well a signal ranks what actually happens
next, roughly a correlation between prediction and outcome. Cheap to compute, so
it is the first filter: about 50× cheaper than a backtest.

**Overfitting** — finding a pattern in noise. Test enough variations and one will
look excellent by chance alone. The defence is counting how many were tried and
correcting for it.

**CPCV (Combinatorial Purged Cross-Validation)** — splitting history into many
train/test combinations, with gaps that prevent information leaking across the
boundary. Produces a *distribution* of results rather than one number, which
matters because you will trade exactly one path and it may be a bad one.

**Deflated Sharpe Ratio (DSR)** — a performance score adjusted for how many
strategies were tried before this one was picked. The headline number in this
project.

**PBO (Probability of Backtest Overfitting)** — the estimated probability that
the configuration chosen is actually worse than average out of sample.

**Holdout** — a slice of recent history locked away and read exactly once, by
the operator's action, at the final gate. Read it twice and it stops being a
holdout.

**Pre-registration** — writing down the hypothesis, the parameters to be tried
and *how many* configurations will be tested, before touching the data. The
number is what makes the statistics honest.

**Sharpe ratio** — return divided by volatility. Roughly, how much reward per
unit of stomach-churning. 1.0 is good; above 3.0, assume a data bug until
proven otherwise.

---

## Trading and execution

**Slippage** — the gap between the price you expected and the price you got.

**Market impact** — your own order moving the price against you. Grows roughly
with the square root of size relative to volume, so it is the reason a strategy
that works at ₹1 lakh may not work at ₹1 crore.

**Lot size** — the fixed quantity one derivatives contract covers. In India it
is revised periodically, which is why it is stored as a time-versioned field and
never hardcoded.

**OMS / EMS** — Order Management System (tracks the lifecycle of every order) and
Execution Management System (decides how to work it into the market).

**Idempotent client order ID** — a deterministic identifier per order, so that
retrying after a network timeout cannot accidentally place a second one. This
single pattern prevents the most expensive category of retail algo bug.

**Reconciliation** — continuously comparing our record of positions and cash
against the broker's. The broker is always right; our copy is a cache.

**Kill switch** — an independent mechanism that stops trading and flattens
positions, running in a separate process with separate credentials, so it still
works when the main system is wedged.

**SPAN margin** — the exchange's method of calculating margin on a derivatives
portfolio by stressing it across price and volatility scenarios.

**STT** — Securities Transaction Tax. Rates differ by instrument and, critically,
option *exercise* is taxed on notional rather than premium — which can exceed
the value of a marginally in-the-money option.

**F&O ban period** — when a stock's derivatives open interest exceeds a limit, no
new positions are allowed. Backtests that ignore this take trades that would have
been rejected.

---

## This project's own machinery

**Sprint** — one session of work, one runnable thing, one review page.

**ADR (Architecture Decision Record)** — five lines recording a choice: what was
decided, what was rejected, and what it costs if it turns out wrong.

**`make verify`** — the single command that runs every gate and prints one table.

**Stub** — something deliberately fake, logged in `docs/STUBS.md` the moment it
is created.

**Trial counter** — a tamper-evident log of every strategy configuration ever
evaluated. Without it, the overfitting statistics are theatre.
