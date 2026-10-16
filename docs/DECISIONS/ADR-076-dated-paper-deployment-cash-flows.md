# ADR-076 — Date paper deployment cash flows

**Status:** Accepted · 2026-10-15

## Context

Paper deployments replay every decision from their start using the original
capital. Editing that capital changes historical sizing, which conflicts with
the OMS journal's rule that an already-traded day cannot change. External
deposits and withdrawals need an effective date in that replay.

## Decision

Record each paper cash flow with its signed amount, the latest decision date
already completed when it was entered, and its entry timestamp. Apply it at the
first later decision close and force sizing there. Existing days keep the
original capital and orders. Deposits are available to the following session's
fills. Withdrawals lower target sizing and are paid only after resulting sells
settle; the route refuses an outflow that would leave less than ₹1,000.
Overnight deployments apply flows after the previous position settles at the
open and before the next close's sizing. Live deployments reject cash flows.

State separates applied flows, pending flows and contributed capital. The
reported total return links subperiod returns around external flows, so a
deposit is not counted as profit. Telegram reports the gain against contributed
capital.

The event-driven engine's cash-flow argument is optional and defaults to none;
backtests retain their existing behavior.

## Consequences

- The original capital remains an immutable replay starting value.
- A replay after a flow can place orders only on decisions after the recorded
  date; journalled orders remain idempotent.
- A withdrawal may wait for next-session sells to settle before cash leaves the
  paper book.
- The Paper trading card can show pending and completed flows for audit.
