# Bajpai deep reinforcement learning paper: reproducibility audit

**Review date:** 2026-10-15
**Disposition:** reject as evidence of an intraday strategy; method details are insufficient for a faithful local implementation.
**Research Library record:** `bajpai-2021-deep-rl-india`

## Source and method recovered

Bajpai, “Application of deep reinforcement learning for Indian stock trading
automation,” [arXiv:2106.16088](https://arxiv.org/html/2106.16088), compares DQN,
Double DQN and Dueling Double DQN over ten Nifty 50 stock datasets. The full
HTML reports hold/buy/sell actions and a nominal 50/50 training/test division
with the later period used for testing. Listed hyperparameters include a
90-step window, 50 episodes, batch size 64, gamma 0.95, learning rate 0.00025,
epsilon from 1.0 to a 0.1 floor with 0.995 decay, Adam and mean-squared error.

The result tables report profit in currency units by stock and model. For
example, Dueling DDQN's test profits range from ₹57 for TATASTEEL to ₹101,731
for NESTLEIND. The paper does not state a common starting capital alongside
these figures, so they cannot be compared as return percentages or net results.

## Why no strategy/backtest was created

The source does not specify the state vector (what goes into the 90-step
window), reward function, neural-network dimensions, exact position-sizing and
action semantics, bar frequency, or order/execution logic. It also omits costs,
spreads and slippage. Without those choices, a local implementation would be a
new design that happens to use a DQN, not a replication of the paper. The
paper's frequency is unspecified, so the results are not established as
intraday.

This agent architecture is different from the existing Gini and ETC decision
trees, but a model-family difference alone does not provide a fixed, testable
strategy. The Research Library record has been updated from “abstract only” to
the method details actually present in the full paper and marked rejected as
intraday profitability evidence. No Strategy Library card or local result is
claimed.

## Evidence required to reconsider

An author implementation or detailed appendix must provide the exact state
features, reward, architecture, data frequency and date range, starting
capital, position constraints, and order timing. A local test would then need a
chronological train/test schedule, purged labels where the reward looks
forward, multiple stocks with point-in-time membership, date-aware NSE costs,
spread/slippage assumptions and a held-out evaluation period.
