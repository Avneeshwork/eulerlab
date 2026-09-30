# ADR-035 — Count trials by family, and control the false discovery rate

**Date:** 2026-08-20 · **Sprint:** fleet scale-up · **Status:** **PROPOSED —
operator decision required**

> `CLAUDE.md`: *`gates.py` and `mandate.yaml` are operator-owned. You may
> propose changes in a review; you may not edit them without an explicit
> instruction in that session.* Nothing has been changed. This is the proposal.

**Context.** The operator wants a fleet of hundreds to thousands of strategies
across several asset classes. Every configuration evaluated appends a trial,
and the bar rises with the count. Run on our own function, 1,000 trials puts
the bar at Sharpe **3.26**; the best result this project has ever produced is
**1.27**. A flat counter therefore makes the fleet unpublishable by arithmetic
before any strategy in it is even wrong — the gate would kill all of it, and
would be right to given what it was told. Research note 015 has the table and
the sources.

**Options.**
(a) Keep flat counting. Honest, and ends the fleet idea — at scale the gate
becomes a formality that always says KILL.
(b) Stop counting exploratory runs. Cheap, and it is the failure mode the
ledger exists to prevent: searching you do not pay for is exactly how a
backtest gets laundered.
(c) Count by **family** — one pre-registered economic idea — with an
effective-N correction for correlation *within* the family, and control the
**false discovery rate across families** (Benjamini–Hochberg–Yekutieli)
instead of the family-wise error rate across every configuration.

**Choice.** (c), if the operator accepts it.

**Why.** Our current expected-max-Sharpe correction is FWER-shaped: it asks
what the best of N pure-noise strategies would score, controlling the chance of
promoting *any* false positive. That is the right instrument for a handful of
pre-registered candidates and the wrong one for a fleet, where it is so
punishing that no true discovery can survive it either. Harvey, Liu & Zhu
(2016) make exactly this argument for the factor zoo and recommend BHY (§3.4.3,
§3.3), and they treat correlation among test statistics as a first-class
problem rather than an inconvenience (§4).

The correlation point is the load-bearing one, and it is not a loophole. Fifty
parameter variants of one momentum idea are not fifty independent bets on the
market; they are one bet, measured fifty ways, and their returns are correlated
accordingly. Counting them as fifty overstates the search — but *only* if the
family was pre-registered before the variants were run. Registering a family
after seeing which variants worked is fitting the accounting to the answer, and
the ledger's hash chain is what makes the ordering checkable.

This project has already done the same computation in a different place:
`features/independence.py` clusters the feature sweep and reports that ten
features amount to roughly three findings. The proposal is that arithmetic
applied to strategy returns rather than feature values.

**Two conditions this is not worth doing without.**

1. **The ledger must start recording per-trial Sharpe (A-021).** The bar is
   scaled by σ_SR, the dispersion of Sharpes across trials, hardcoded to 1.0
   and documented nowhere. At σ_SR = 0.5 the bar at 19 trials is 0.94 and the
   best-ever 1.27 would clear it; at 1.5 it is 2.82 and every past verdict was
   too lenient. **It cannot currently be measured** — only 3 of 19 ledger
   entries carry a Sharpe and all three are the same hypothesis, so the number
   the whole correction is scaled by is the one the ledger never wrote down.
   This is a schema change that applies going forward only; the existing 19
   entries cannot be back-filled. Rebuilding the accounting on an unmeasurable
   constant would be building on the wrong thing.
2. **The estimator for effective N needs a primary source (A-020).** The
   direction is well sourced; the specific method is not yet.

**Cost if wrong.** **High, and asymmetric — this is the one to be careful
about.** Every other decision in this project errs toward refusing things; this
one loosens a gate, which is the direction that costs money rather than
opportunity. If families are drawn too broadly, or registered after the fact,
the effective N is understated, the bar drops, and a noise strategy is
promoted with a certificate saying it is not noise. The existing flat counter
cannot fail that way — its failure mode is refusing everything, which costs
only opportunity.

Two guards follow from that. The family and its grid are **pre-registered in
the card before any variant runs**, so the count cannot be fitted to the
result. And the ledger records the family id, the grid cardinality and the
estimated effective N on every entry, so a later reader can recompute the bar
and see whether the accounting was honest. Neither guard is free to skip.
