# 110 — GitHub 3-bar ATR momentum burst: NSE screen

**Date:** 2026-10-15 · **Status:** backtested; negative net result

## Source and fixed rule

The [source strategy](https://github.com/luckyloneranger/backtest-platform/blob/main/strategies/strategies/deterministic/intraday_momentum.py)
uses 5-minute bars. After a six-bar warmup it checks whether the close-to-close
move over three bar intervals exceeds 1.5 ATR(14), and requires current-bar
volume above twice the preceding up-to-20-bar mean. It enters in the move's
direction and trails a stop by one ATR. The source allows up to two trades per
symbol and exits at 15:00.

The GitHub README lists this as one component of a strategy platform. Its
positive +32%/+39% claim is for a regime-adaptive portfolio, so it does not
establish that this momentum component works by itself. This screen isolates
that signal and does not borrow the combined portfolio's headline return.

## NSE adaptation

- Fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY.
- Compute Wilder ATR(14) and volume mean from completed 5-minute bars within
  each session. Require a three-interval close-to-close move greater than 1.5
  ATR and signal-bar volume above 2x the preceding 20-bar average.
- Enter at the next contiguous 5-minute open. Initialize the stop one ATR from
  the signal close, then update a 1 ATR trailing stop only after each completed
  bar. A gap through the stop fills at the open; if touched intrabar, assume the
  stop fills before any favorable movement.
- Allow at most two round trips per stock per session. Flatten at 15:00. Size
  each position at 3% of ₹1,000,000 total capital, capped at ₹200,000 per
  stock. This is source-style notional sizing, not a 3% risk budget.
- Apply date-aware NSE intraday charges plus 2 bp assumed slippage per side.
- Evaluate 2024-01-01 through 2024-11-30. Files crossing the cutoff are
  excluded; this is a fixed development sample and will not be tuned.

This impulse entry differs from the existing surge-pullback trigger, which
requires a pullback and a higher-high continuation. Both sit in the broader
momentum family, so this is a distinct source-defined candidate rather than a
claim of a wholly separate market effect.

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 929 |
| Gross return / Sharpe | +0.05% / 0.222 |
| Net return / Sharpe | **−3.82% / −14.622** |
| Net maximum drawdown | −3.82% |
| Net winners / profit factor | 189 / 929 (20.3%) / 0.276 |
| Estimated fees and slippage | ₹39,464 |

Gross return was only +0.05%, and modeled costs made the net result materially
negative. This standalone rule does not qualify as profitable and will not be
tuned against this sample. The source's combined portfolio result is not
attributed to this rule.

Run `make github-momentum-burst-intraday` to reproduce. Results will be stored
in `data/derived/github_momentum_burst_stock_strategies.json`; `make
library-sync` attaches the measured run to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_momentum_burst_screen.py`.

## Limits

Five current stocks are not a point-in-time universe. Minute OHLCV does not
contain spread, depth, queue position or partial fills. The assumed slippage
and OHLC stop ordering affect results. The source's combined portfolio result
cannot be used as evidence for this isolated signal.
