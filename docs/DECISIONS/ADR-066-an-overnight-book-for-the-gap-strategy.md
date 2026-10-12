# ADR-066 — The Nifty overnight strategy gets its own paper book

**Context.** Operator, 2026-10-12: "Paper-deploying the gap strategy".
`nifty_calm_rise_overnight` buys the Nifty future at one close and sells at the
next open. A deployment replays a `Strategy` through the equity engine, which
fills once a day at the close, so the strategy could be studied and not
deployed (T-4048). `CLAUDE.md` asks for one `Strategy` interface across
backtest, paper and live, and says to fix the abstraction when they diverge.

**Options.** (a) Teach the engine a second fill time per day and a futures
position, and move the strategy onto the `Strategy` interface. (b) A runner of
its own for this strategy, sharing everything else a deployment has. (c) Leave
it undeployable.

**Choice.** (b): `deploy/overnight.py`. It reuses the study's signal function
(`gap_forecast.predict`), and the equity books' OMS, journal, paper broker,
deterministic order ids, kill switch, halt-on-disagreement and state file. Only
the loop that decides what to send on which day is its own.

**Why.** (a) is the right end state and is a change to the engine every
gated result ran on; doing it for one strategy that is not a gate candidate
(Sharpe 0.64, flat since 2024) risks the many for the one. The strategy was
already outside the interface, like Tweezer (ADR-037); (b) does not widen that
exception, it lets the existing one be watched forward. What must never
diverge is the order path, and that is shared.

**Cost if wrong.** Two decision loops to keep honest. A test holds the book's
nights and contracts to the study's on real history. If a second overnight or
futures strategy appears, (a) stops being optional: do it then, and retire this
runner.

**Sizing, stated because it decides whether the book trades at all.** Whole
lots, up to the book's own equity in notional, no borrowing: the study's
assumption. One lot was 65 units and ₹14.7 lakh on 2026-10-09, so a smaller
book never trades and says so each signal night. The lot size is read from the
day's F&O file, never written in code.
