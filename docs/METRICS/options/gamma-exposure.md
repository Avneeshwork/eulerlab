# Gamma exposure (GEX) by strike

*Family: Options. Id: `gamma-exposure`.*

**In one line:** Gamma times open interest per strike, signed on an assumption about who holds the options.

**Where you see it:** Options charts.

**How we compute it:** (call gamma × call OI − put gamma × put OI) × forward² × 0.01 per strike (`options/analytics.gamma_exposure`).

**Data and freshness:** Bhavcopy.

**What is normal (our data, as of 2026-10-30):** Not computed.

**How to read it:**

- Positive totals are usually read as dealers damping moves; negative as dealers amplifying them.

**What it does not tell you:** Who is actually long or short. The sign assumes dealers are long calls and short puts, which the bhavcopy cannot show.

**Traps:**

- If the sign assumption is wrong for Nifty, support and resistance point at the wrong strikes.
- The idea comes from SqueezeMetrics' 2017 paper on US markets, which we have not read in full.

**Related:**

- [greeks](../options/greeks.md)
- [max-pain](../options/max-pain.md)

**Sources:**

- SqueezeMetrics, Gamma Exposure (2017), via third-party summaries; the paper was not fetched (2026-10-31).

## Example answers

**Q:** GEX is negative. Will it be volatile?

**A:** Only if the usual assumption about who holds the options is right for Nifty, which we cannot check. Treat it as a hypothesis, not a reading.
