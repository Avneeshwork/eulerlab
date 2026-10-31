# Gate verdict and the holdout

*Family: Validation and the gate. Id: `gate-verdict`.*

**In one line:** PROMOTE or KILL from every check above; then one read of the held-back data.

**Where you see it:** `make gate`; Strategies page.

**How we compute it:** `gates.decide` against `mandate.yaml`; a check that cannot be evaluated fails (`docs/ARCHITECTURE.md` §5.8).

**Data and freshness:** Validation outputs, ledger, evidence.

**What is normal (our data, as of 2026-10-30):** Everything evaluated so far has been killed (`docs/ARCHITECTURE.md` §5.3).

**How to read it:**

- Binary by design. A killed strategy is not tuned and resubmitted.

**What it does not tell you:** A forecast.

**Traps:**

- The holdout is read once, by the operator, only after PROMOTE; never 'to check something'.

**Related:**

- [deflated-sharpe](../validation/deflated-sharpe.md)
- [pbo](../validation/pbo.md)
- [stress-tests](../validation/stress-tests.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.8; `CLAUDE.md` Validation rules.

## Example answers

**Q:** It failed only PBO. Can we tweak and rerun?

**A:** No. A strategy that fails the gate is dead, and re-running it adds trials that raise the bar for everything else.
