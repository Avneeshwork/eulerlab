# 130 — How does the research agent get smarter, and improve itself, without spending the trial bar?

**Date:** 2026-10-31 · **Confidence:** high on what each paper reports; low that any LLM-found signal survives this gate on Indian data (no paper tests a gate this strict)

Full report and plan for the operator: Claude Doc "Making the research agent self-improving" (https://claude.ai/artifact/PeUsiAsudk9jk3c6SWDbzG).

## Question

The operator sent TradingAgents (arXiv 2412.20138) and asked how the research agent can become more intelligent, improve itself and produce profitable strategies.

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| Xiao et al., TradingAgents (v7, 2025) | https://arxiv.org/abs/2412.20138 | 2026-10-31 | Full PDF (operator upload) |
| AlphaAgent (KDD 2025) | https://arxiv.org/html/2502.16789v2 | 2026-10-31 | Method and results |
| R&D-Agent(Q) | https://arxiv.org/html/2505.15155v2 | 2026-10-31 | Method and results; limitations not reached |
| Navigating the Alpha Jungle (LLM + MCTS) | https://arxiv.org/html/2505.11122v3 | 2026-10-31 | Method only; result tables not reached |
| QuantAgent | https://ar5iv.labs.arxiv.org/html/2402.03755 | 2026-10-31 | Method and results |
| FINSABER | https://arxiv.org/html/2505.07078v5 | 2026-10-31 | First 100,000 characters |
| ExpeL | https://arxiv.org/html/2308.10144v3 | 2026-10-31 | Method and results |
| AlphaEvolve | https://arxiv.org/abs/2506.13131 | 2026-10-31 | Abstract |
| Lopez-Lira et al., The Memorization Problem | https://arxiv.org/html/2504.14765v2 | 2026-10-31 | Findings and remedies |
| Chronologically Consistent LLMs | https://arxiv.org/html/2502.21206v3 | 2026-10-31 | Method and findings |
| Dwork et al., The reusable holdout (Google Research blog) | https://www.research.google/blog/the-reusable-holdout-preserving-validity-in-adaptive-data-analysis/ | 2026-10-31 | Whole post |
| McLean and Pontiff (2016) | https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf | 2026-10-31 | Abstract |
| Novy-Marx and Velikov, AI-Powered (Finance) Scholarship | https://www.nber.org/papers/w33363 | 2026-10-31 | Abstract |
| Yu, Li and You, LiveTradeBench | https://www.arxiv.org/abs/2511.03628 | 2026-10-31 | Abstract |

## Findings

1. TradingAgents tests 1 Jan to 29 Mar 2024 on AAPL, GOOGL and AMZN, reports Sharpe 8.21 on AAPL (the authors say this exceeds the expected range) and mentions no transaction costs. Each decision used 11 LLM calls and 20+ tool calls.
2. FINSABER re-tested LLM trading agents over two decades and 100+ symbols: the advantages "deteriorate significantly". FinMem's published TSLA Sharpe 2.679 replicated as 0.927.
3. AlphaAgent: penalties for similarity to a known alpha zoo (largest common AST subtree), hypothesis-formula misalignment and complexity. CSI 500 2021-24: IC 0.0212, 11.00% annual excess return, IR 1.488; S&P 500: IC 0.0056, IR 1.0545. Its alphas held IC near 0.02 while Alpha158 and similar decayed toward zero. Results are from 20 runs of 5 rounds.
4. R&D-Agent(Q): the LLM sees only the data schema, not raw data or split dates; a linear Thompson-sampling bandit chooses factor vs model work and beat random and LLM choice (IC 0.0532 vs 0.0445 and 0.0476); new factors with IC correlation >= 0.99 to the current set are dropped; under $10 a run. CSI 300 test 2017 to Aug 2020: IC 0.0532, IR 1.74.
5. Alpha Jungle: candidates scored on effectiveness, stability, turnover, diversity and overfitting risk; refinement targets the weakest; frequent subtrees are avoided for diversity.
6. QuantAgent: writer/judge inner loop plus real-feedback outer loop; single-alpha gains "not clearly significant"; one year of A-share data.
7. ExpeL: insights maintained with ADD, EDIT, UPVOTE, DOWNVOTE; removed at zero; no weight updates.
8. GPT-4o recalls index levels and macro figures before its cutoff; an instruction to ignore later data left accuracy at 97.6% vs 98.0%; masked earnings calls were still identified. Post-cutoff data should be the primary test.
9. Adaptive reuse of a test set overfits it; access through a rationed, noisy mechanism keeps it valid (Dwork et al.).
10. 97 predictors: returns 26% lower out of sample, 58% lower after publication (McLean and Pontiff).
11. Novy-Marx and Velikov mined 30,000+ signals, kept 96 and had LLMs write papers with invented rationales: AI can "industrialize HARKing".
12. LiveTradeBench: 21 LLMs over 50 live days; chatbot leaderboard rank did not predict trading results.

## What could not be found

- No paper tests LLM-mined signals against a deflated-Sharpe or PBO gate, or on Indian equities.
- Chain-of-Alpha (arXiv 2508.06312) is withdrawn by its author; not used.
- Jensen, Kelly and Pedersen's replication study was read only through a secondary summary, which did not say whether India is covered; not used.

## Decision

Proposed, not built. The constraint is our own trial bar (research 015): 1.88 at 19 trials, 2.84 at 250. The idea lab's 5 a week is about 260 a year. So the agent must improve its pass rate per trial, not its trial count. Plan: a typed formula language interpreted over `MarketView` (no generated Python); a discovery window (proposed 2015-2020) searched freely and logged in a separate exploration log; one real trial per candidate on a confirmation window (2021 to the card's holdout) that returns pass or fail only; AlphaAgent's three penalties; weakest-score refinement and a bandit; an ExpeL-style lessons list whose entries must cite stored experiences; a graveyard; a zero-trial test bench of synthetic planted-signal panels for judging new prompts or models. Whether discovery searches count against the gate is operator-owned (`gates.py`, `mandate.yaml`) and is put to the operator; see TASKS T-4214.

## Open questions

1. Does the operator accept that discovery-window searches are not gate trials when the gate judges agent cards on confirmation data only?
2. The window boundaries.
3. Whether a paid model may write hypotheses and lessons, and the monthly cap once Phase 3 measures cost.
