# ADR-178 — A CUSUM on live returns against the backtest says healthy, watch or decayed

**Date:** 2026-11-13. **Status:** accepted; measured on made-up returns only (T-4590). Issue #147 under #134.

- **Context.** Paper books stop at fixed drawdowns. A strategy whose edge has gone but loses slowly keeps its capital; an unlucky good one can be halted. A fund that runs itself has to tell the two apart.
- **Options.** (a) A rolling Sharpe below a threshold. (b) SPRT. (c) A one-sided CUSUM with its alarm level set from the strategy's own backtest.
- **Choice.** (c), research 191. `deploy/decay.py`: `read(backtest, live)` gives the state, the statistic and the level. The level is calibrated per strategy by block-resampling its backtest to the constitution's `decay.false_alarm` over `decay.horizon_sessions`; `watch` starts at `decay.watch_at` of it. Measured slippage is taken off the backtest mean, and slippage drift alone means watch. `delay` reports how often and how fast a strategy with no edge left would be caught.
- **Why.** A rolling Sharpe has no stated false-alarm rate. CUSUM is the standard tool for a small, lasting shift, and calibrating on the strategy's own returns keeps fat tails and clustering in the alarm level instead of assuming them away.
- **Cost if wrong.** It is slow by nature: at 5% false alarms a dead strategy with a backtest Sharpe near 2.4 is caught in 250 sessions about two times in three. If the backtest overstates the edge, a healthy-but-weaker strategy will read as decayed, which is the right answer to the wrong baseline. The three settings are the thread's (A-139). The Live & Risk page does not show the state yet (T-4590).
