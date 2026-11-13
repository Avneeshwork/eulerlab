# 189 — What paid models cost, and how a spent holdout can still be rationed

**Question.** Two facts the constitution and the firewall figures depend on (ADR-171, ADR-172). What does each Claude model in `config/llm.yaml` cost per token? Can a period that will be looked at many times still say something?

## Sources

| Source | URL | Fetched |
|---|---|---|
| Anthropic, Pricing | https://platform.claude.com/docs/en/about-claude/pricing.md | 2026-11-12 |
| Google Research blog on Dwork, Feldman, Hardt, Pitassi, Reingold and Roth, "The reusable holdout", Science 2015 | https://research.google/blog/the-reusable-holdout-preserving-validity-in-adaptive-data-analysis/ | 2026-11-12 |
| Harvey, Liu and Zhu, "... and the Cross-Section of Expected Returns", NBER w20592 (abstract) | https://nber.org/papers/w20592 | 2026-11-12 |
| Bailey, Borwein, López de Prado and Zhu, "The Probability of Backtest Overfitting", SSRN 2326253 (abstract) | https://papers.ssrn.com/abstract=2326253 | 2026-11-12 |

## Findings

**Prices**, US dollars per million tokens, base input / output: Claude Fable 5.2 8 / 40; Fable 5.1 10 / 50; Opus 5.5 4 / 20; Sonnet 5.5 2 / 10; Haiku 5.5 0.10 / 0.50 for prompts up to 100,000 tokens (0.50 / 2.50 above). Cache writes and reads are priced separately and are not used here.

At Rs 90 a dollar (A-135, not fetched), Rs 1,000 a month is about $11. An autopilot request is taken as 6,000 tokens in and 4,000 out (an estimate; the earlier measured cost was about 5 US cents a request): about Rs 4.7 on Sonnet 5.5, Rs 9.4 on Opus 5.5. One Sonnet request a night is about Rs 140 a month. The allowed five a night, every night, would be about Rs 700, which leaves Rs 300 for every other paid request.

**The reusable holdout.** The blog says a holdout reached only through a mechanism that limits what each answer reveals "maintains the essential guarantees of fresh data over the course of many estimation steps", and that the number of uses grows roughly with the square of the holdout's size. The mechanism in the paper (Thresholdout) answers from the training set unless the holdout disagrees by more than a noisy threshold.

**Multiple testing.** Harvey, Liu and Zhu: a new factor "needs to clear a much higher hurdle, with a t-ratio greater than 3.0". Bailey et al. estimate the probability of backtest overfitting from all the variants tried, by combinatorially symmetric cross-validation; `validation/statistics.py` already has it.

## Decision

- The constitution's price table uses the figures above; a paid model without a price is charged at 10 / 50.
- `validation/firewall.holds` returns one bit per rule (kept half its discovery Sharpe on the selection period, after a nudge of up to 0.25 fixed by the rule's fingerprint), not the selection Sharpe. This is in the spirit of Thresholdout, not an implementation of it: there is no formal privacy budget, and the constants are chosen by hand (A-136).

## Confidence and what was not found

Prices: high on the fetch date; they change, so A-135's row carries a recheck date. Haiku's higher tier for long prompts is not modelled; no agent sends prompts that long.

Not read: the Science paper itself (only the authors' blog), so the noise distribution and the exact guarantee are not checked. Not found: a published choice of threshold for a Sharpe-ratio query, or an online false-discovery method fitted to a stream of trading rules (#139 still owes that note). The selection period 2024-2025 was already read for fifteen strategies (ADR-143), which no mechanism undoes.
