# ADR-115: The daily engines and the paper runner refuse short weights

- **Context:** The 2026-11-01 backtester review (HISTORY #53) found both engines accepted negative weights and held a short overnight in cash equity, which Indian delivery does not allow, and Tier B's realised P&L booked a short sale's proceeds as profit. No registered daily strategy returns a negative weight. The operator said go on T-4363.
- **Options:** (a) Leave it. (b) Model shorts properly: borrow through SLBM, margin, square-off and P&L. (c) Refuse negative weights.
- **Choice:** (c). `strategy.long_only` drops a negative weight before `normalise`, in Tier A, Tier B and the paper preview, and each result counts it as `refused_shorts`. The longs keep their own weights; nothing is rescaled into the gap.
- **Why:** It matches what can be held in a delivery account, keeps the two engines agreeing, and changes no stored result, since no strategy here shorts.
- **Cost if wrong:** A long-short idea is tested as its long half, which may look worse or better than the real thing. Shorting through futures or SLBM needs (b), which is a sprint of its own.
