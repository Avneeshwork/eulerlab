# ADR-139 — The validation battery for intraday rules

**Context.** H-0096 (short on the first F&O ban day) passed the intraday screen and the operator asked for it to be gated (2026-11-06). `make validate` only re-runs daily `rank_and_hold` strategies, so it could not produce an evidence pack for a same-day trading rule.

**Options.** (a) Gate intraday rules by hand from the screen output; (b) teach the event-driven engine intraday fills; (c) score the battery from the rule's own trades.

**Choice.** (c): `validation/intraday.py`. CPCV paths, deflated Sharpe, the search bar and Romano-Wolf all read the rule's daily net returns; the stresses the gate reads (`costs x2`, `drop best 5 names`, `regime: first/second half`) are recomputed from the trades, plus `costs x3` and `entry 5 minutes late`. Purge horizon 1 session. One configuration, so PBO is 0 over 0 paths, as the statistic defines it. Only hypotheses listed in `SOURCES` are accepted. `gates.py` and `mandate.yaml` are unchanged.

**Why.** It uses the same trades the screen reported, so the gate judges exactly what was screened, and it reuses every existing statistic rather than writing new ones.

**Cost if wrong.** The stresses are re-derived, not re-simulated: a fill that would change under 2x costs (it would not here) is not modelled, and a single-configuration PBO says nothing. Paper trading is the check on both.
